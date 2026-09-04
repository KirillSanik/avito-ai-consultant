"""Полная история коммитов и дерево файлов репозитория через git CLI (FR-002, FR-003).

История — весь вывод ``git log`` (без усечения), merge-коммиты исключены (``--no-merges``).

Транспортный формат истории — ``%H``, ``%an``, ``%aI``, ``%s``, разделённые
байтом unit separator (``%x1f``): git не экранирует subject (`%s`) и имя
автора (`%an`), поэтому JSON-строки вида ``{"message":"%s"}`` ломаются на
абсолютно штатных коммитах (например, ``Revert "..."``). Байт ``0x1f`` в
subject практически невозможен; при его наличии разбор падает явно
(``MetadataExtractionError``) — fail-loud по data-model.md §1. В промпт
история попадает в pipe-формате контракта (llm-structured-output.md §4),
т.е. транспортный формат не виден LLM.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ._spawn import spawn_git
from .utils.exceptions import MetadataExtractionError
from .utils.models import CommitInfo

logger = logging.getLogger(__name__)

#: Разделитель полей в строке истории: байт unit separator (``%x1f`` в pretty-format git).
_FIELD_SEPARATOR = "\x1f"

#: Формат строки истории (``hash`` / ``author`` / ``date ISO`` / ``subject``) —
#: единый аргумент argv; источники полей — data-model.md §1.
COMMIT_LOG_FORMAT = "--pretty=format:%H%x1f%an%x1f%aI%x1f%s"


async def _run_git(repo_path: Path, *args: str) -> tuple[int, bytes, bytes]:
    """Запуск git-команды в каталоге репозитория; возвращает (код возврата, stdout, stderr).

    Сбой запуска (например, git CLI недоступен) оборачивается в
    ``MetadataExtractionError`` — наружу пробрасывается только доменная
    иерархия ``AIDetectionError`` (FR-013, contracts/public-api.md §2–3).
    """
    try:
        process = await spawn_git("git", "-C", str(repo_path), *args)
    except OSError as exc:
        raise MetadataExtractionError(
            f"Не удалось запустить git для команды «git {' '.join(args)}» "
            "(проверьте, что git CLI установлен и доступен в PATH): "
            f"{exc}"
        ) from exc
    stdout, stderr = await process.communicate()
    return process.returncode, stdout, stderr


def _git_error_detail(returncode: int, command: str, stderr: bytes) -> str:
    lines = stderr.decode("utf-8", errors="replace").strip().splitlines()
    tail = "\n".join(lines[-3:]) if lines else "stderr git пуст"
    return f"{command} завершился с кодом {returncode}: {tail}"


class GitMetadataExtractor:
    """Извлекает из локального репозитория пару ``(история коммитов, дерево файлов)``."""

    async def extract(self, repo_path: Path) -> tuple[list[CommitInfo], list[str]]:
        """Полная история коммитов (merge-коммиты исключены) + список файлов из индекса git."""
        extract_started = time.perf_counter()
        commits = await self._extract_commits(repo_path)
        file_tree = await self._extract_file_tree(repo_path)
        logger.info("Метаданные извлечены за %.3f с: коммитов=%d, файлов=%d", time.perf_counter() - extract_started, len(commits), len(file_tree))
        return commits, file_tree

    async def _extract_commits(self, repo_path: Path) -> list[CommitInfo]:
        logger.debug("git log: извлечение истории коммитов…")
        step_started = time.perf_counter()
        returncode, stdout, stderr = await _run_git(repo_path, "log", COMMIT_LOG_FORMAT, "--no-merges")
        if returncode != 0:
            if returncode == 128 and "does not have any commits yet" in stderr.decode("utf-8", errors="replace"):
                return []
            raise MetadataExtractionError(_git_error_detail(returncode, "git log", stderr))
        try:
            stdout_text = stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.error("git log: история коммитов не в UTF-8")
            raise MetadataExtractionError(
                "История коммитов содержит байты вне UTF-8 и не может быть разобрана"
            ) from exc
        commits: list[CommitInfo] = []
        for line_number, line in enumerate(stdout_text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                commits.append(_parse_commit_line(line))
            except ValueError as exc:  # ValidationError наследуется от ValueError
                raise MetadataExtractionError(
                    f"Не удалось разобрать историю коммитов: строка {line_number} "
                    f"не соответствует схеме CommitInfo"
                ) from exc
        logger.debug("git log: разобрано %d коммитов за %.3f с", len(commits), time.perf_counter() - step_started)
        return commits

    async def _extract_file_tree(self, repo_path: Path) -> list[str]:
        logger.debug("git ls-files: извлечение дерева файлов…")
        step_started = time.perf_counter()
        returncode, stdout, stderr = await _run_git(repo_path, "ls-files")
        if returncode != 0:
            logger.error("git ls-files завершился с кодом %d", returncode)
            raise MetadataExtractionError(_git_error_detail(returncode, "git ls-files", stderr))
        file_tree = [line.strip() for line in stdout.decode("utf-8").splitlines() if line.strip()]
        logger.debug("git ls-files: %d файлов за %.3f с", len(file_tree), time.perf_counter() - step_started)
        return file_tree


def _parse_commit_line(line: str) -> CommitInfo:
    """Разбирает строку истории ``hash␟author␟date␟subject`` в ``CommitInfo``.

    Некорректное число полей — явная ошибка разбора (fail-loud, data-model.md §1);
    валидацию полей (hash-regex, ISO 8601, однострочность) выполняет pydantic.
    """
    fields = line.split(_FIELD_SEPARATOR)
    if len(fields) != 4:
        raise ValueError(f"ожидалось 4 поля (hash/author/date/subject), получено {len(fields)}")
    commit_hash, author, date, message = fields
    return CommitInfo(hash=commit_hash, author=author, date=date, message=message)
