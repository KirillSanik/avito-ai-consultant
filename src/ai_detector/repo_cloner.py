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
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ._spawn import spawn_git
from .utils.exceptions import RepoCloneError

logger = logging.getLogger(__name__)

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


def _mask_secrets(value: str, token: str | None, temp_dir_name: str) -> str:
    """Маскирует токен и путь к temp-каталогу в тексте сообщения об ошибке.

    Токен никогда не попадает в сообщение (FR-011); путь к временному
    каталогу в обязательной части сообщения не фигурирует (public-api.md §3).
    """
    masked = value
    if token:
        masked = masked.replace(token, "***")
    if temp_dir_name:
        masked = masked.replace(temp_dir_name, "***")
    return masked


def _clone_failure_message(repo_url: str, tail: str, token: str | None, temp_dir_name: str) -> str:
    """Русское сообщение о сбое: причина + хвост stderr (токен и temp-путь замаскированы)."""
    message = f"Не удалось клонировать репозиторий {repo_url}: {_mask_secrets(tail, token, temp_dir_name)}"
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
        clone_started = time.perf_counter()
        logger.debug("Создание temp-каталога и запуск git clone…")
        temp_dir = tempfile.TemporaryDirectory(prefix="ai-detector-")
        try:
            repo_path = Path(temp_dir.name) / "repo"
            try:
                process = await spawn_git("git", "clone", clone_url, str(repo_path))
            except OSError as exc:
                logger.error("git clone: не удалось запустить git для %s", repo_url)
                raise RepoCloneError(
                    f"Не удалось запустить git для клонирования {repo_url} "
                    "(проверьте, что git CLI установлен и доступен в PATH): "
                    f"{exc}"
                ) from exc
            try:
                # asyncio.TimeoutError — отдельный класс на Python 3.10 (алиас с 3.11).
                _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=CLONE_TIMEOUT_SECONDS)
            except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 — на Python 3.10 (requires-python) это разные классы
                process.kill()
                await process.wait()
                raise RepoCloneError(
                    f"Не удалось клонировать репозиторий {repo_url}: операция не завершилась "
                    f"за {CLONE_TIMEOUT_SECONDS} с"
                ) from None
            returncode = process.returncode
            if returncode != 0:
                logger.error("git clone %s завершился с кодом %d за %.3f с", repo_url, returncode, time.perf_counter() - clone_started)
                raise RepoCloneError(_clone_failure_message(repo_url, _stderr_tail(stderr), token, temp_dir.name))
            logger.info("git clone %s выполнен за %.3f с", repo_url, time.perf_counter() - clone_started)
            yield repo_path
        finally:
            cleanup_started = time.perf_counter()
            temp_dir.cleanup()
            logger.debug("Temp-каталог удалён за %.3f с", time.perf_counter() - cleanup_started)
