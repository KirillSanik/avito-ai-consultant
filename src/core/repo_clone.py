"""Общее клонирование репозитория через git CLI во временный каталог (ТЗ §5.1, пункт 2).

Функция ``clone_repo`` **возвращает путь** к локальному клону и **не содержит**
логики автоудаления (никаких контекстных менеджеров) — гарантированная очистка
temp-каталога лежит на вызывающем (``core.pipeline.Pipeline``, блок ``finally``
после ``asyncio.gather``).

Сохранена логика прежнего ``ai_detector.repo_cloner.RepoCloner`` (FR-002,
FR-010, FR-011, FR-013): токен ``x-access-token`` для github.com только в
аргументе subprocess, таймаут 120 с, маскирование токена и temp-пути в
сообщениях об ошибке, доменное ``RepoCloneError``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ai_detector.utils.exceptions import RepoCloneError
from common.spawn import spawn_git

logger = logging.getLogger(__name__)

#: Ограничение времени клонирования, секунд (ТЗ §4.2, сохранено из RepoCloner).
CLONE_TIMEOUT_SECONDS = 120

#: Префикс временных каталогов клона (единственный для всего сервиса).
TEMP_DIR_PREFIX = "avito-review-"

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


def _default_git_token() -> str | None:
    """Токен приватных репозиториев: ``AI_DETECTOR_GIT_TOKEN`` > ``GITHUB_TOKEN``.

    Окружение читается напрямую (как прежний ``common.config.git_token()``),
    чтобы каждый вызов видел актуальные значения, а не кешированные настройки.
    """
    return os.getenv("AI_DETECTOR_GIT_TOKEN") or os.getenv("GITHUB_TOKEN")


def _stderr_tail(stderr: bytes, limit: int = 3) -> str:
    """Хвост stderr (последние строки) для сообщения об ошибке."""
    lines = stderr.decode("utf-8", errors="replace").strip().splitlines()
    if not lines:
        return "stderr git пуст"
    return "\n".join(lines[-limit:])


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
    """Маскирует токен и имя temp-каталога в тексте сообщения об ошибке (FR-011)."""
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


async def clone_repo(repo_url: str, *, token: str | None = None, timeout_seconds: float | None = None) -> Path:
    """Клонировать ``repo_url`` во временный каталог и вернуть путь к репозиторию.

    Временный корень (``mkdtemp`` с префиксом :data:`TEMP_DIR_PREFIX`) содержит
    один каталог ``repo`` — возвращаемый путь. При любом сбое клонирования
    корень удаляется (:func:`shutil.rmtree`) **до** проброса
    ``RepoCloneError``; при успехе очисткой занимается вызывающий.

    :param repo_url: URL репозитория (https или локальный путь).
    :param token: токен для приватных репозиториев; ``None`` — взять из окружения.
    :param timeout_seconds: ограничение времени клонирования, секунд;
        ``None`` — :data:`CLONE_TIMEOUT_SECONDS` (чтение модульного имени
        в момент вызова — тестируемость сокращённым таймаутом).
    """
    if token is None:
        token = _default_git_token()
    effective_timeout = CLONE_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    clone_url = _inject_token(repo_url, token)
    clone_started = time.perf_counter()
    logger.info("Клонирование репозитория %s во временный каталог…", repo_url)
    temp_root = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX)
    repo_path = Path(temp_root) / "repo"
    try:
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
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=effective_timeout)
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 — на Python 3.10 (requires-python) это разные классы
            process.kill()
            await process.wait()
            raise RepoCloneError(
                f"Не удалось клонировать репозиторий {repo_url}: операция не завершилась "
                f"за {effective_timeout} с"
            ) from None
        returncode = process.returncode
        if returncode != 0:
            logger.error(
                "git clone %s завершился с кодом %d за %.3f с",
                repo_url,
                returncode,
                time.perf_counter() - clone_started,
            )
            raise RepoCloneError(_clone_failure_message(repo_url, _stderr_tail(stderr), token, temp_root))
    except BaseException:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    logger.info("git clone %s выполнен за %.3f с", repo_url, time.perf_counter() - clone_started)
    return repo_path
