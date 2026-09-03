"""Юнит-тесты GitMetadataExtractor: полный лог коммитов + список файлов через git CLI (FR-002, FR-003).

Подмена: asyncio.create_subprocess_exec (FakeGitProcess) — два вызова: git log и git ls-files.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_detector.exceptions import MetadataExtractionError
from ai_detector.git_metadata import GitMetadataExtractor
from ai_detector.models import CommitInfo

REPO = Path("/tmp/fake-clone") / "repo"

HASH_1 = "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12"
HASH_2 = "cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34"

COMMIT_1 = {
    "hash": HASH_1,
    "author": "student",
    "date": "2026-03-01T14:22:05+03:00",
    "message": "первый коммит",
}
COMMIT_2 = {
    "hash": HASH_2,
    "author": "student",
    "date": "2026-03-02T09:15:00+03:00",
    "message": "добавлен LRU-кеш",
}

PRETTY_FORMAT = "--pretty=format:%H%x1f%an%x1f%aI%x1f%s"
FIELD_SEP = "\x1f"


class FakeGitProcess:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(0)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self._returncode


class GitHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._queue: list[FakeGitProcess] = []

    def enqueue(self, process: FakeGitProcess) -> None:
        self._queue.append(process)

    async def fake_create_subprocess_exec(self, *args: object, **_kwargs: object) -> FakeGitProcess:
        self.calls.append(tuple(str(arg) for arg in args))
        return self._queue.pop(0) if self._queue else FakeGitProcess()


@pytest.fixture
def git(monkeypatch: pytest.MonkeyPatch) -> GitHarness:
    harness = GitHarness()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", harness.fake_create_subprocess_exec)
    return harness


def log_stdout(commits: list[dict[str, str]]) -> bytes:
    return (
        "\n".join(FIELD_SEP.join(commit[key] for key in ("hash", "author", "date", "message")) for commit in commits)
    ).encode("utf-8")


async def test_extract_returns_commits_and_file_tree(git: GitHarness) -> None:
    """Полная история: список CommitInfo в порядке git log + дерево файлов."""
    git.enqueue(FakeGitProcess(stdout=log_stdout([COMMIT_2, COMMIT_1])))
    git.enqueue(FakeGitProcess(stdout="lru.py\nREADME.md\n".encode("utf-8")))
    commits, file_tree = await GitMetadataExtractor().extract(REPO)
    assert commits == [CommitInfo(**COMMIT_2), CommitInfo(**COMMIT_1)]
    assert file_tree == ["lru.py", "README.md"]


async def test_git_log_command_contains_pretty_format_and_no_merges(git: GitHarness) -> None:
    """FR-002: git log содержит точно --pretty=format:'...' и --no-merges."""
    git.enqueue(FakeGitProcess(stdout=log_stdout([COMMIT_1])))
    git.enqueue(FakeGitProcess(stdout=b""))
    await GitMetadataExtractor().extract(REPO)
    (log_args, ls_args) = git.calls
    assert log_args[0] == "git"
    assert str(REPO) in log_args
    assert "log" in log_args
    assert PRETTY_FORMAT in log_args  # формат — единый аргумент argv
    assert "--no-merges" in log_args
    assert ls_args[0] == "git"
    assert str(REPO) in ls_args
    assert "ls-files" in ls_args


async def test_broken_log_line_raises_with_line_number(git: GitHarness) -> None:
    """Битая строка (не 4 поля) → MetadataExtractionError с номером строки."""
    broken_line = "\nэто не история коммитов"
    git.enqueue(FakeGitProcess(stdout=log_stdout([COMMIT_1]) + broken_line.encode("utf-8")))
    git.enqueue(FakeGitProcess(stdout=b""))
    with pytest.raises(MetadataExtractionError) as exc_info:
        await GitMetadataExtractor().extract(REPO)
    assert "строка 2" in str(exc_info.value)


async def test_commit_subject_with_quotes_is_parsed(git: GitHarness) -> None:
    """Subject с кавычками (Revert \"...\") разбирается — регрессия JSON-транспорта.

    Git не экранирует `%s`/`%an`: JSON-строки лога ломались на штатных
    Revert-коммитах; транспорт теперь разделён байтом unit separator.
    """
    commit = dict(
        COMMIT_1,
        message='Revert "delete CONTRIBUTING.rst"',
        author='O\'Neil, "Tony"',
    )
    git.enqueue(FakeGitProcess(stdout=log_stdout([COMMIT_2, commit])))
    git.enqueue(FakeGitProcess(stdout=b""))
    commits, _ = await GitMetadataExtractor().extract(REPO)
    assert commits[1] == CommitInfo(**commit)


async def test_invalid_commit_fields_raise_metadata_error(git: GitHarness) -> None:
    """Невалидные поля коммита (короткий hash) → MetadataExtractionError."""
    bad_commit = dict(COMMIT_1, hash="short")
    git.enqueue(FakeGitProcess(stdout=log_stdout([COMMIT_2, bad_commit])))
    git.enqueue(FakeGitProcess(stdout=b""))
    with pytest.raises(MetadataExtractionError) as exc_info:
        await GitMetadataExtractor().extract(REPO)
    assert "строка 2" in str(exc_info.value)


async def test_git_log_failure_raises_metadata_error(git: GitHarness) -> None:
    """git log завершился с ошибкой → MetadataExtractionError с контекстом git."""
    git.enqueue(FakeGitProcess(returncode=128, stderr=b"fatal: not a git repository"))
    with pytest.raises(MetadataExtractionError) as exc_info:
        await GitMetadataExtractor().extract(REPO)
    assert "not a git repository" in str(exc_info.value)


async def test_repo_without_commits_yields_empty_history(git: GitHarness) -> None:
    """Репозиторий без коммитов → пустая история без исключения (граница FR-003)."""
    stderr = b"fatal: your current branch 'master' does not have any commits yet"
    git.enqueue(FakeGitProcess(returncode=128, stderr=stderr))
    git.enqueue(FakeGitProcess(stdout=b"lru.py\n"))
    commits, file_tree = await GitMetadataExtractor().extract(REPO)
    assert commits == []
    assert file_tree == ["lru.py"]


async def test_ls_files_failure_raises_metadata_error(git: GitHarness) -> None:
    """Ошибка git ls-files → MetadataExtractionError."""
    git.enqueue(FakeGitProcess(stdout=log_stdout([COMMIT_1])))
    git.enqueue(FakeGitProcess(returncode=128, stderr=b"fatal: not a git repository"))
    with pytest.raises(MetadataExtractionError) as exc_info:
        await GitMetadataExtractor().extract(REPO)
    assert "not a git repository" in str(exc_info.value)


async def test_git_spawn_oserror_raises_metadata_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-013: OSError при запуске git (CLI недоступен) → MetadataExtractionError, а не «сырой» OSError."""

    async def raising_spawn(*_args: object, **_kwargs: object) -> FakeGitProcess:
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", raising_spawn)
    with pytest.raises(MetadataExtractionError) as exc_info:
        await GitMetadataExtractor().extract(REPO)
    assert "git" in str(exc_info.value)
