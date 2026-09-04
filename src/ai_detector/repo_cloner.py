"""Совместимость прежнего API ``RepoCloner`` поверх общего ``core.repo_clone``.

Логика клонирования (токен, таймаут, маскирование, ошибки) вынесена в
``core.repo_clone.clone_repo`` — единственная реализация. ``RepoCloner``
остался тонким асинхронным контекстным менеджером для обратной
совместимости (CLI/тесты и публичный контракт public-api.md §1): внутри
тела доступен путь к клону, при любом выходе из контекста (успех,
исключение, отмена) temp-каталог гарантированно удаляется (FR-010, SC-004).

Пайплайн API-сервиса контекстный менеджер не использует: он вызывает
``clone_repo`` сам и чистит каталог в ``finally`` (ТЗ §5.1).
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from core.repo_clone import TEMP_DIR_PREFIX, clone_repo

__all__ = ["TEMP_DIR_PREFIX", "RepoCloner", "clone_repo"]


class RepoCloner:
    """Клонирование репозитория в одноразовый временный каталог (обёртка над ``clone_repo``).

    ``clone`` — асинхронный контекстный менеджер: внутри тела доступен
    путь к локальной копии репозитория, при выходе каталог удаляется.
    """

    @asynccontextmanager
    async def clone(self, repo_url: str) -> AsyncIterator[Path]:
        repo_path = await clone_repo(repo_url)
        try:
            yield repo_path
        finally:
            # Родитель каталога — временный корень ``mkdtemp`` (префикс TEMP_DIR_PREFIX).
            shutil.rmtree(repo_path.parent, ignore_errors=True)
