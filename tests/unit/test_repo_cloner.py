"""Юнит-тесты RepoCloner: subprocess git clone в изолированном временном каталоге (FR-002, FR-010).

Подмена: asyncio.create_subprocess_exec (FakeGitProcess).
Реальные проверки: точный argv git clone, код возврата, таймаут 120 с
(через сокращённый CLONE_TIMEOUT_SECONDS), гарантированное удаление временного каталога.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import ai_detector.repo_cloner as repo_cloner_module
from ai_detector.exceptions import RepoCloneError
from ai_detector.repo_cloner import RepoCloner

REPO_URL = "https://github.com/owner/repo.git"
PRIVATE_URL = "https://github.com/owner/private-repo.git"
TOKEN = "ghp_secret-token-123"


class FakeGitProcess:
    """Имитация асинхронного subprocess: communicate() / wait() / kill()."""

    def __init__(self, returncode: int = 0, stderr: bytes = b"", hang: bool = False) -> None:
        self._returncode = returncode
        self._stderr = stderr
        self._hang = hang
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.Event().wait()  # никогда не завершается — имитация зависания
        await asyncio.sleep(0)
        return b"", self._stderr

    async def wait(self) -> int:
        return self._returncode

    def kill(self) -> None:
        self.killed = True


class ClonerHarness:
    """Захватывает вызовы create_subprocess_exec и выдаёт заранее поставленные FakeGitProcess."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.processes: list[FakeGitProcess] = []
        self._queue: list[FakeGitProcess] = []

    def enqueue(self, process: FakeGitProcess) -> None:
        self._queue.append(process)

    async def fake_create_subprocess_exec(self, *args: object, **_kwargs: object) -> FakeGitProcess:
        self.calls.append(tuple(str(arg) for arg in args))
        process = self._queue.pop(0) if self._queue else FakeGitProcess()
        self.processes.append(process)
        return process


@pytest.fixture
def cloner(monkeypatch: pytest.MonkeyPatch) -> ClonerHarness:
    harness = ClonerHarness()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", harness.fake_create_subprocess_exec)
    return harness


@pytest.fixture
def clean_token_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Убирает токены из окружения, чтобы тесты не зависели от внешнего окружения."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AI_DETECTOR_GIT_TOKEN", raising=False)
    return monkeypatch


async def test_clone_launches_exact_git_argv(cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch) -> None:
    """FR-002: запускается git clone <url> <путь> с точным argv."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(REPO_URL) as repo_path:
        assert isinstance(repo_path, Path)
    (args,) = cloner.calls
    assert args[:3] == ("git", "clone", REPO_URL)
    assert args[3] == str(repo_path)  # точный путь — тот, что возвращён в тело контекста


async def test_clone_success_removes_temp_dir(cloner: ClonerHarness) -> None:
    """FR-010: временный каталог удалён после успешного анализа."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(REPO_URL) as repo_path:
        pass
    assert not repo_path.exists()


async def test_clone_nonzero_exit_raises_repo_clone_error(cloner: ClonerHarness) -> None:
    """Код возврата git != 0 → RepoCloneError с контекстом из stderr."""
    stderr = b"Cloning into '/x/repo'...\nfatal: repository not found\n"
    cloner.enqueue(FakeGitProcess(returncode=128, stderr=stderr))
    with pytest.raises(RepoCloneError) as exc_info:
        async with RepoCloner().clone(REPO_URL):
            pass
    message = str(exc_info.value)
    assert "Не удалось" in message
    assert "fatal: repository not found" in message  # хвост stderr сохранён


async def test_clone_timeout_raises_repo_clone_error_and_kills_process(
    cloner: ClonerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Таймаут клонирования → RepoCloneError, процесс убит."""
    monkeypatch.setattr(repo_cloner_module, "CLONE_TIMEOUT_SECONDS", 0.05)
    cloner.enqueue(FakeGitProcess(hang=True))
    with pytest.raises(RepoCloneError) as exc_info:
        async with RepoCloner().clone(REPO_URL):
            pass
    assert "Не удалось" in str(exc_info.value)
    assert cloner.processes[0].killed is True


async def test_clone_removes_temp_dir_when_body_raises(cloner: ClonerHarness) -> None:
    """FR-010: временный каталог удалён даже при ошибке в теле контекста."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    with pytest.raises(ValueError):
        async with RepoCloner().clone(REPO_URL) as repo_path:
            raise ValueError("сбой в теле анализа")
    assert not repo_path.exists()


async def test_clone_injects_github_token_into_subprocess_url(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """FR-011: GITHUB_TOKEN подставляется в URL как x-access-token (только для аргумента subprocess)."""
    clean_token_env.setenv("GITHUB_TOKEN", TOKEN)
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(PRIVATE_URL):
        pass
    (args,) = cloner.calls
    assert args[:2] == ("git", "clone")
    assert args[2] == f"https://x-access-token:{TOKEN}@github.com/owner/private-repo.git"


async def test_ai_detector_git_token_takes_priority_over_github_token(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """AI_DETECTOR_GIT_TOKEN имеет приоритет над GITHUB_TOKEN."""
    clean_token_env.setenv("GITHUB_TOKEN", "other-token")
    clean_token_env.setenv("AI_DETECTOR_GIT_TOKEN", TOKEN)
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(PRIVATE_URL):
        pass
    (args,) = cloner.calls
    assert args[2] == f"https://x-access-token:{TOKEN}@github.com/owner/private-repo.git"


async def test_public_url_without_token_is_not_modified(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """Без токена в окружении URL передаётся в git без изменений."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(REPO_URL):
        pass
    (args,) = cloner.calls
    assert args[2] == REPO_URL


async def test_token_not_injected_for_non_github_urls(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """Токен подставляется только для https://github.com — другие хосты не трогаются."""
    clean_token_env.setenv("GITHUB_TOKEN", TOKEN)
    gitlab_url = "https://gitlab.com/owner/repo.git"
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(gitlab_url):
        pass
    (args,) = cloner.calls
    assert args[2] == gitlab_url


async def test_token_absent_from_error_message_when_git_output_contains_it(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """FR-011: токен из вывода git маскируется — в str(exc) его нет."""
    clean_token_env.setenv("GITHUB_TOKEN", TOKEN)
    stderr = (
        f"fatal: unable to access 'https://x-access-token:{TOKEN}@github.com/owner/private-repo.git/': "
        "The requested URL returned error: 403\n"
    ).encode("utf-8")
    cloner.enqueue(FakeGitProcess(returncode=128, stderr=stderr))
    with pytest.raises(RepoCloneError) as exc_info:
        async with RepoCloner().clone(PRIVATE_URL):
            pass
    message = str(exc_info.value)
    assert "Не удалось" in message
    assert TOKEN not in message
    assert "***" in message


async def test_private_repo_without_token_raises_clear_error(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """Приватный репозиторий без токена → RepoCloneError с подсказкой о правах/токене (FR-013)."""
    stderr = b"fatal: repository 'https://github.com/owner/private-repo.git/' not found\n"
    cloner.enqueue(FakeGitProcess(returncode=128, stderr=stderr))
    with pytest.raises(RepoCloneError) as exc_info:
        async with RepoCloner().clone(PRIVATE_URL):
            pass
    message = str(exc_info.value)
    assert "Не удалось" in message
    assert "GITHUB_TOKEN" in message  # подсказка, что для приватного репозитория нужен токен
