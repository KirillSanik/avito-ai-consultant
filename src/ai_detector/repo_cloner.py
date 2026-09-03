"""Клонирование репозитория через git CLI в изолированный временный каталог (FR-002, FR-010).

Временный каталог гарантированно удаляется при любом выходе из контекста —
успех, исключение или отмена (SC-004).

Для приватных репозиториев токен читается из переменных окружения
(``GITHUB_TOKEN``, переопределение ``AI_DETECTOR_GIT_TOKEN``) и подставляется
в URL клонирования как ``x-access-token`` **только** в аргумент subprocess:
в сообщения об ошибках и логи токен не попадает (FR-011, research.md §3).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .exceptions import RepoCloneError

#: Ограничение времени клонирования, секунд (ТЗ §4.2).
CLONE_TIMEOUT_SECONDS = 120

#: Хосты, для которых токен подставляется как ``x-access-token`` (research.md §3).
_GITHUB_HOSTS: frozenset[str] = frozenset({"github.com", "www.github.com"})

#: Маркеры сбоев доступа в stderr git — при них в ошибку добавляется
#: подсказка о токене/правах (FR-013, quickstart.md §6).
_ACCESS_FAILURE_MARKERS: tuple[str, ...] = (
    "could not read username",
    "authentication failed",
    "invalid credentials",
    "access denied",
    "not found",
    "returned error: 403",
    "returned error: 404",
)


def _stderr_tail(stderr: bytes, limit: int = 3) -> str:
    """Хвост stderr (последние строки) для сообщения об ошибке."""
    lines = stderr.decode("utf-8", errors="replace").strip().splitlines()
    if not lines:
        return "stderr git пуст"
    return "\n".join(lines[-limit:])


def _git_token_from_env() -> str | None:
    """Токен из окружения: ``AI_DETECTOR_GIT_TOKEN`` имеет приоритет над ``GITHUB_TOKEN``."""
    return os.environ.get("AI_DETECTOR_GIT_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def _inject_token(repo_url: str, token: str | None) -> str:
    """Возвращает URL клонирования для аргумента subprocess.

    При наличии токена и URL вида ``https://github.com/...`` токен
    подставляется как ``x-access-token`` (research.md §3). Для других
    схем/хостов и без токена URL не модифицируется.
    """
    if token is None:
        return repo_url
    parts = urlsplit(repo_url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in _GITHUB_HOSTS:
        return repo_url
    netloc = f"x-access-token:{token}@{parts.hostname}"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _mask_secret(value: str, token: str | None) -> str:
    """Маскирует токен в тексте, чтобы он не попал в сообщение об ошибке (FR-011)."""
    if token:
        return value.replace(token, "***")
    return value


def _clone_failure_message(repo_url: str, tail: str, token: str | None) -> str:
    """Русское сообщение о сбое: причина + хвост stderr (токен замаскирован)."""
    message = f"Не удалось клонировать репозиторий {repo_url}: {_mask_secret(tail, token)}"
    lowered = tail.lower()
    if any(marker in lowered for marker in _ACCESS_FAILURE_MARKERS):
        message += (
            " — репозиторий недоступен или не существует; для приватных репозиториев задайте "
            "переменную окружения GITHUB_TOKEN (переопределение: AI_DETECTOR_GIT_TOKEN)"
        )
    return message


class RepoCloner:
    """Клонирование репозитория в одноразовый временный каталог.

    ``clone`` — асинхронный контекстный менеджер: внутри тела доступен
    путь к локальной копии репозитория, при выходе каталог удаляется.
    """

    @asynccontextmanager
    async def clone(self, repo_url: str) -> AsyncIterator[Path]:
        token = _git_token_from_env()
        clone_url = _inject_token(repo_url, token)
        temp_dir = tempfile.TemporaryDirectory(prefix="ai-detector-")
        try:
            repo_path = Path(temp_dir.name) / "repo"
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                clone_url,
                str(repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=CLONE_TIMEOUT_SECONDS)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise RepoCloneError(
                    f"Не удалось клонировать репозиторий {repo_url}: операция не завершилась "
                    f"за {CLONE_TIMEOUT_SECONDS} с"
                ) from None
            returncode = await process.wait()
            if returncode != 0:
                raise RepoCloneError(_clone_failure_message(repo_url, _stderr_tail(stderr), token))
            yield repo_path
        finally:
            temp_dir.cleanup()
