"""Полная история коммитов и дерево файлов репозитория через git CLI (FR-002, FR-003).

История — весь вывод ``git log`` (без усечения), merge-коммиты исключены (``--no-merges``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import ValidationError

from .exceptions import MetadataExtractionError
from .models import CommitInfo

#: Формат JSON-строк истории — единый аргумент argv (контракт contracts/llm-structured-output.md).
COMMIT_LOG_FORMAT = '--pretty=format:{"hash":"%H","author":"%an","date":"%aI","message":"%s"}'


async def _run_git(repo_path: Path, *args: str) -> tuple[int, bytes, bytes]:
    """Запуск git-команды в каталоге репозитория; возвращает (код возврата, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_path),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    returncode = await process.wait()
    return returncode, stdout, stderr


def _git_error_detail(returncode: int, command: str, stderr: bytes) -> str:
    lines = stderr.decode("utf-8", errors="replace").strip().splitlines()
    tail = "\n".join(lines[-3:]) if lines else "stderr git пуст"
    return f"{command} завершился с кодом {returncode}: {tail}"


class GitMetadataExtractor:
    """Извлекает из локального репозитория пару ``(история коммитов, дерево файлов)``."""

    async def extract(self, repo_path: Path) -> tuple[list[CommitInfo], list[str]]:
        """Полная история коммитов (merge-коммиты исключены) + список файлов из индекса git."""
        commits = await self._extract_commits(repo_path)
        file_tree = await self._extract_file_tree(repo_path)
        return commits, file_tree

    async def _extract_commits(self, repo_path: Path) -> list[CommitInfo]:
        returncode, stdout, stderr = await _run_git(repo_path, "log", COMMIT_LOG_FORMAT, "--no-merges")
        if returncode != 0:
            if returncode == 128 and "does not have any commits yet" in stderr.decode("utf-8", errors="replace"):
                return []
            raise MetadataExtractionError(_git_error_detail(returncode, "git log", stderr))
        commits: list[CommitInfo] = []
        for line_number, line in enumerate(stdout.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw_commit = json.loads(line)
                commits.append(CommitInfo(**raw_commit))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise MetadataExtractionError(
                    f"Не удалось разобрать историю коммитов: строка {line_number} "
                    f"не соответствует формату JSON/схемы CommitInfo"
                ) from exc
        return commits

    async def _extract_file_tree(self, repo_path: Path) -> list[str]:
        returncode, stdout, stderr = await _run_git(repo_path, "ls-files")
        if returncode != 0:
            raise MetadataExtractionError(_git_error_detail(returncode, "git ls-files", stderr))
        return [line.strip() for line in stdout.decode("utf-8").splitlines() if line.strip()]
