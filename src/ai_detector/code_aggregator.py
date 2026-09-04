"""Агрегация полного исходного кода репозитория с маркерами разделителей (FR-004, FR-005, FR-014).

Содержимое каждого файла передаётся целиком, без усечения; чтение —
асинхронное (aiofiles) и ограничено семафором параллельных чтений.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import time
from pathlib import Path

import aiofiles

from .utils.exceptions import CodeAggregationError

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
        self._max_concurrent_reads = max_concurrent_reads
        self._semaphore = asyncio.Semaphore(max_concurrent_reads)

    async def aggregate(self, repo_path: Path) -> str:
        """Полный исходный код всех поддерживаемых файлов, без усечения (FR-004).

        Блоки ``--- FILE: <path> --- ... --- END FILE ---`` соединены пустой строкой.
        """
        aggregate_started = time.perf_counter()
        try:
            # Блокирующий обход дерева (rglob/stat) — вне event loop.
            relative_paths = await asyncio.to_thread(self._collect_files, repo_path)
        except OSError as exc:
            logger.error("Агрегация: не удалось перечислить файлы репозитория")
            raise CodeAggregationError(f"Не удалось перечислить файлы репозитория: {exc}") from exc
        if not relative_paths:
            logger.error("Агрегация: поддерживаемых исходных файлов не найдено")
            raise CodeAggregationError("no supported source files")
        logger.debug("Агрегация: чтение %d файлов (параллельно до %d)…", len(relative_paths), self._max_concurrent_reads)
        contents = await asyncio.gather(*(self._read_file(repo_path / rel) for rel in relative_paths))
        blocks: list[str] = []
        # strict=True: списки равной длины по построению (gather по тому же списку путей).
        for rel, content in zip(relative_paths, contents, strict=True):
            if content is None:
                continue
            if not content.endswith("\n"):
                content += "\n"
            blocks.append(f"--- FILE: {rel} ---\n{content}--- END FILE ---")
        if not blocks:
            logger.error("Агрегация: ни один поддерживаемый файл не прочитан как UTF-8")
            raise CodeAggregationError("ни один поддерживаемый файл не удалось прочитать как текст UTF-8")
        result = "\n\n".join(blocks)
        logger.info(
            "Агрегация кода завершена за %.3f с: файлов=%d, объём=%d символов",
            time.perf_counter() - aggregate_started,
            len(blocks),
            len(result),
        )
        return result

    def _collect_files(self, repo_path: Path) -> list[str]:
        """Отсортированные относительные пути поддерживаемых файлов (белый/чёрный списки, FR-005).

        Обход — ``os.walk`` с обрезкой исключённых директорий: в ``node_modules``/``venv``
        и т.п. не спускаемся вовсе (в отличие от наивного ``rglob`` с пост-фильтром).
        """
        relative_paths: list[str] = []
        for dirpath, dirnames, filenames in os.walk(repo_path):
            # Фильтруем dirnames in-place — os.walk не спустится в отсечённые каталоги.
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for filename in filenames:
                if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                full_path = Path(dirpath) / filename
                relative_paths.append(full_path.relative_to(repo_path).as_posix())
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
