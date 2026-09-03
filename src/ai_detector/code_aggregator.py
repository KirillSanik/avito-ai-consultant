"""Агрегация полного исходного кода репозитория с маркерами разделителей (FR-004, FR-005, FR-014).

Содержимое каждого файла передаётся целиком, без усечения; чтение —
асинхронное (aiofiles) и ограничено семафором параллельных чтений.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiofiles

from .exceptions import CodeAggregationError

logger = logging.getLogger(__name__)

#: Поддерживаемые расширения (регистронезависимо) — FR-005.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".py", ".go", ".rs", ".js", ".ts", ".java", ".cpp", ".md"})

#: Исключаемые директории (любой вложенности) — FR-005.
EXCLUDED_DIRS: frozenset[str] = frozenset({".git", "__pycache__", "venv", "node_modules", ".idea", ".vscode"})

#: Лимит параллельных чтений файлов — FR-014.
MAX_CONCURRENT_READS = 20


class LocalCodeAggregator:
    """Собирает весь исходный код репозитория в одну строку с маркерами файлов."""

    def __init__(self, max_concurrent_reads: int = MAX_CONCURRENT_READS) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent_reads)

    async def aggregate(self, repo_path: Path) -> str:
        """Полный исходный код всех поддерживаемых файлов, без усечения (FR-004).

        Блоки ``--- FILE: <path> --- ... --- END FILE ---`` соединены пустой строкой.
        """
        relative_paths = self._collect_files(repo_path)
        if not relative_paths:
            raise CodeAggregationError("no supported source files")
        contents = await asyncio.gather(*(self._read_file(repo_path / rel) for rel in relative_paths))
        blocks: list[str] = []
        for rel, content in zip(relative_paths, contents):
            if content is None:
                continue
            blocks.append(f"--- FILE: {rel} ---\n{content}--- END FILE ---")
        if not blocks:
            raise CodeAggregationError("ни один поддерживаемый файл не удалось прочитать как текст UTF-8")
        return "\n\n".join(blocks)

    def _collect_files(self, repo_path: Path) -> list[str]:
        """Отсортированные относительные пути поддерживаемых файлов (белый/чёрный списки, FR-005)."""
        relative_paths: list[str] = []
        for path in repo_path.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            parts = path.relative_to(repo_path).parts
            if any(part in EXCLUDED_DIRS for part in parts):
                continue
            relative_paths.append(path.relative_to(repo_path).as_posix())
        return sorted(relative_paths)

    async def _read_file(self, file_path: Path) -> str | None:
        """Содержимое файла целиком под семафором; бинарные (не UTF-8) файлы пропускаются."""
        async with self._semaphore:
            try:
                async with aiofiles.open(file_path, encoding="utf-8") as handle:
                    return await handle.read()
            except UnicodeDecodeError:
                logger.warning("Файл %s не является текстом UTF-8 и пропущен", file_path)
                return None
            except OSError as exc:
                raise CodeAggregationError(f"Не удалось прочитать файл {file_path}: {exc}") from exc
