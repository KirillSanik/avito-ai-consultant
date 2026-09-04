"""Юнит-тесты клонирования: ``core.repo_clone.clone_repo`` и обёртка ``RepoCloner`` (FR-002, FR-010, FR-011).

Подмена: asyncio.create_subprocess_exec (FakeGitProcess) и tempfile модуля
``core.repo_clone`` (захват имени temp-каталога).

Реальные проверки: точный argv git clone, код возврата, таймаут 120 с
(через сокращённый ``CLONE_TIMEOUT_SECONDS``), удаление temp-каталога при
сбое (авто) и на выходе из контекста ``RepoCloner`` (обратная совместимость),
маскирование токена и temp-пути в сообщениях об ошибке.

Замечание: ``clone_repo`` **не** удаляет каталог при успехе (ТЗ §5.1,
пункт 2) — очистку проверяют тесты ``RepoCloner`` и ``core.pipeline``.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile as real_tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.repo_clone as repo_clone_module
from ai_detector.repo_cloner import RepoCloner
from ai_detector.utils.exceptions import RepoCloneError
from core.repo_clone import TEMP_DIR_PREFIX, clone_repo

REPO_URL = "https://github.com/owner/repo.git"
PRIVATE_URL = "https://github.com/owner/private-repo.git"
TOKEN = "ghp_secret-token-123"


class FakeGitProcess:
    """Имитация асинхронного subprocess: communicate() / wait() / kill()."""

    def __init__(self, returncode: int = 0, stderr: bytes = b"", hang: bool = False) -> None:
        self.returncode = returncode
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


def _cleanup(*paths: Path | str) -> None:
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


async def test_clone_repo_launches_exact_git_argv(cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch) -> None:
    """FR-002: запускается git clone <url> <путь> с точным argv; возвращается путь <root>/repo."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    repo_path = await clone_repo(REPO_URL)
    (args,) = cloner.calls
    assert args[:3] == ("git", "clone", REPO_URL)
    assert args[3] == str(repo_path)
    assert repo_path.name == "repo"
    assert repo_path.parent.name.startswith(TEMP_DIR_PREFIX)
    _cleanup(repo_path.parent)


async def test_clone_repo_success_leaves_temp_dir_for_caller(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """ТЗ §5.1 пункт 2: при успехе автоудаления нет — каталог живёт до очистки вызывающим."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    repo_path = await clone_repo(REPO_URL)
    try:
        assert repo_path.parent.exists()
    finally:
        _cleanup(repo_path.parent)


async def test_clone_repo_nonzero_exit_raises_and_removes_temp(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Код возврата git != 0 → RepoCloneError с контекстом из stderr; temp-каталог удалён."""
    holder: dict[str, str] = {}
    real_mkdtemp = real_tempfile.mkdtemp

    def recording_mkdtemp(**kwargs: object) -> str:
        name = real_mkdtemp(**kwargs)
        holder["name"] = name
        return name

    monkeypatch.setattr(repo_clone_module, "tempfile", SimpleNamespace(mkdtemp=recording_mkdtemp))
    stderr = b"Cloning into '/x/repo'...\nfatal: repository not found\n"
    cloner.enqueue(FakeGitProcess(returncode=128, stderr=stderr))
    with pytest.raises(RepoCloneError) as exc_info:
        await clone_repo(REPO_URL)
    message = str(exc_info.value)
    assert "Не удалось" in message
    assert "fatal: repository not found" in message  # хвост stderr сохранён
    assert not Path(holder["name"]).exists()  # временный корень удалён при сбое  # noqa: ASYNC240


async def test_clone_repo_timeout_raises_and_kills_process(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Таймаут клонирования → RepoCloneError, процесс убит, temp-каталог удалён."""
    monkeypatch.setattr(repo_clone_module, "CLONE_TIMEOUT_SECONDS", 0.05)
    cloner.enqueue(FakeGitProcess(hang=True))
    with pytest.raises(RepoCloneError) as exc_info:
        await clone_repo(REPO_URL)
    assert "Не удалось" in str(exc_info.value)
    assert cloner.processes[0].killed is True


async def test_clone_repo_cancellation_removes_temp(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-004: отмена во время клонирования → CancelledError, temp-каталог удалён."""
    holder: dict[str, str] = {}
    real_mkdtemp = real_tempfile.mkdtemp

    def recording_mkdtemp(**kwargs: object) -> str:
        name = real_mkdtemp(**kwargs)
        holder["name"] = name
        return name

    monkeypatch.setattr(repo_clone_module, "tempfile", SimpleNamespace(mkdtemp=recording_mkdtemp))
    cloner.enqueue(FakeGitProcess(hang=True))
    task = asyncio.create_task(clone_repo(REPO_URL))
    await asyncio.sleep(0.05)  # дождаться, что клон «завис»
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not Path(holder["name"]).exists()  # noqa: ASYNC240 — sync-проверка в тесте


async def test_clone_repo_injects_github_token_into_subprocess_url(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """FR-011: GITHUB_TOKEN подставляется в URL как x-access-token (только для аргумента subprocess)."""
    clean_token_env.setenv("GITHUB_TOKEN", TOKEN)
    cloner.enqueue(FakeGitProcess(returncode=0))
    repo_path = await clone_repo(PRIVATE_URL)
    (args,) = cloner.calls
    assert args[:2] == ("git", "clone")
    assert args[2] == f"https://x-access-token:{TOKEN}@github.com/owner/private-repo.git"
    _cleanup(repo_path.parent)


async def test_ai_detector_git_token_takes_priority_over_github_token(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """AI_DETECTOR_GIT_TOKEN имеет приоритет над GITHUB_TOKEN."""
    clean_token_env.setenv("GITHUB_TOKEN", "other-token")
    clean_token_env.setenv("AI_DETECTOR_GIT_TOKEN", TOKEN)
    cloner.enqueue(FakeGitProcess(returncode=0))
    repo_path = await clone_repo(PRIVATE_URL)
    (args,) = cloner.calls
    assert args[2] == f"https://x-access-token:{TOKEN}@github.com/owner/private-repo.git"
    _cleanup(repo_path.parent)


async def test_public_url_without_token_is_not_modified(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """Без токена в окружении URL передаётся в git без изменений."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    repo_path = await clone_repo(REPO_URL)
    (args,) = cloner.calls
    assert args[2] == REPO_URL
    _cleanup(repo_path.parent)


async def test_token_not_injected_for_non_github_urls(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """Токен подставляется только для https://github.com — другие хосты не трогаются."""
    clean_token_env.setenv("GITHUB_TOKEN", TOKEN)
    gitlab_url = "https://gitlab.com/owner/repo.git"
    cloner.enqueue(FakeGitProcess(returncode=0))
    repo_path = await clone_repo(gitlab_url)
    (args,) = cloner.calls
    assert args[2] == gitlab_url
    _cleanup(repo_path.parent)


async def test_token_absent_from_error_message_when_git_output_contains_it(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch
) -> None:
    """FR-011: токен из вывода git маскируется — в str(exc) его нет."""
    clean_token_env.setenv("GITHUB_TOKEN", TOKEN)
    stderr = (
        f"fatal: unable to access 'https://x-access-token:{TOKEN}@github.com/owner/private-repo.git/': "
        "The requested URL returned error: 403\n"
    ).encode()
    cloner.enqueue(FakeGitProcess(returncode=128, stderr=stderr))
    with pytest.raises(RepoCloneError) as exc_info:
        await clone_repo(PRIVATE_URL)
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
        await clone_repo(PRIVATE_URL)
    message = str(exc_info.value)
    assert "Не удалось" in message
    assert "GITHUB_TOKEN" in message  # подсказка, что для приватного репозитория нужен токен


async def test_clone_repo_git_spawn_oserror_maps_to_domain_error(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-013: OSError при запуске git (CLI недоступен) → доменный RepoCloneError, а не «сырой» OSError."""

    async def raising_spawn(*_args: object, **_kwargs: object) -> FakeGitProcess:
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", raising_spawn)
    with pytest.raises(RepoCloneError) as exc_info:
        await clone_repo(REPO_URL)
    assert "git" in str(exc_info.value)
    assert type(exc_info.value) is not OSError


async def test_clone_repo_temp_dir_path_masked_in_error_message(
    cloner: ClonerHarness, clean_token_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """public-api.md §3: путь к temp-каталогу из stderr маскируется в сообщении об ошибке."""
    holder: dict[str, str] = {}
    real_mkdtemp = real_tempfile.mkdtemp

    def recording_mkdtemp(**kwargs: object) -> str:
        name = real_mkdtemp(**kwargs)
        holder["name"] = name
        return name

    monkeypatch.setattr(repo_clone_module, "tempfile", SimpleNamespace(mkdtemp=recording_mkdtemp))

    async def fake_create_subprocess_exec(*_args: object, **_kwargs: object) -> FakeGitProcess:
        # stderr со ссылкой на фактический temp-каталог (уже создан до запуска git).
        stderr = (
            f"fatal: unable to access '{holder['name']}/repo': "
            "The requested URL returned error: 404\n"
        ).encode()
        process = FakeGitProcess(returncode=128, stderr=stderr)
        cloner.processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    with pytest.raises(RepoCloneError) as exc_info:
        await clone_repo(REPO_URL)
    message = str(exc_info.value)
    assert holder["name"] not in message
    assert "***" in message


# ---------------------------------------------------------------------------
# Обратная совместимость: RepoCloner (контекстный менеджер) поверх clone_repo
# ---------------------------------------------------------------------------


async def test_repo_cloner_success_removes_temp_dir(cloner: ClonerHarness) -> None:
    """FR-010 (обёртка): временный каталог удалён после выхода из контекста (успех)."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    async with RepoCloner().clone(REPO_URL) as repo_path:
        assert isinstance(repo_path, Path)
        assert repo_path.parent.name.startswith(TEMP_DIR_PREFIX)
    assert not repo_path.parent.exists()


async def test_repo_cloner_removes_temp_dir_when_body_raises(cloner: ClonerHarness) -> None:
    """FR-010 (обёртка): временный каталог удалён даже при ошибке в теле контекста."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    with pytest.raises(ValueError):
        async with RepoCloner().clone(REPO_URL) as repo_path:
            raise ValueError("сбой в теле анализа")
    assert not repo_path.parent.exists()


async def test_repo_cloner_removes_temp_dir_on_cancellation(cloner: ClonerHarness) -> None:
    """SC-004 (обёртка): при отмене задачи временный каталог гарантированно удалён."""
    cloner.enqueue(FakeGitProcess(returncode=0))
    seen: list[Path] = []
    entered = asyncio.Event()

    async def body() -> None:
        async with RepoCloner().clone(REPO_URL) as repo_path:
            seen.append(repo_path)
            entered.set()
            await asyncio.Event().wait()  # имитация долгого анализа внутри контекста

    task = asyncio.create_task(body())
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not seen[0].parent.exists()
