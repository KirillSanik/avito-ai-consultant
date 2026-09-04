"""Регрессия: сбой параллельной ветки (FR-006) в окне запуска git не должен «подвешивать» процесс.

Бихевиор CPython asyncio (наблюдено на 3.10–3.13.3): ``asyncio.gather``
немедленно пробрасывает сбой одной ветки, не отменяя соседние; незавершённая
соседняя ветка (``GitMetadataExtractor`` с вполёте запуском git) отменяется
при shut-down ``asyncio.run`` — ``_cancel_all_tasks`` отменяет **все**
pending-задачи разом, включая внутреннюю задачу
``BaseSubprocessTransport._connect_pipes``. Если она отменена раньше, чем
подключила пайпы, наивный путь отмены CPython (``transp.close(); await
transp._wait()``) зависает навсегда: ``_try_finish()`` требует
подключённых пайпов, ``_wait()`` не разрешается, ``_cancel_all_tasks`` ждёт
вечно — процесс умирает невыходом **без исключения** (сценарий T029: репо
без поддерживаемых файлов, агрегатор падает синхронно, запуск git ещё вполёте).

``common.spawn.spawn_git`` устойчив к этому: запуск идёт в отдельной
``asyncio.shield``-задаче, а если после отмены задача зависла в
``transp._wait()``, короткий дожидающий окно и второй ``cancel()``
гарантируют завершение shut-down.

Тест 1 — детерминированный регресс-сценарий в дочернем процессе:
``asyncio.run`` с ``gather(spawner, sync_failer)`` (failer падает синхронно,
как ``LocalCodeAggregator`` на репо без поддерживаемых файлов). До фикса
процесс зависал; теперь завершается за ограниченный срок.
Тест 2 — пользовательский сценарий: ``analyze()`` на репозитории без
поддерживаемых файлов → ``CodeAggregationError``, temp-каталоги удалены,
pending-задач в loop нет.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from openai import AsyncOpenAI

from ai_detector import AIDetectionService, CodeAggregationError

TASK_CRITERIA = "Критерии: LRU-кэш с ограничением capacity."

#: Дочерний сценарий: реальный запуск git + синхронно падающий сосед
#: (точко форма сбоя T029 в ``service.analyze``: агрегатор падает на первом
#: шаге, git-ветка ещё в окне запуска).
_CHILD_SCRIPT = """
import asyncio
import sys

from common.spawn import spawn_git


async def spawner() -> None:
    process = await spawn_git("git", "-C", sys.argv[1], "log", "--oneline")
    await process.wait()


async def failer() -> None:
    raise RuntimeError("сбой соседа")


async def main() -> None:
    try:
        await asyncio.gather(spawner(), failer())
    except RuntimeError:
        pass
    print("clean-exit")


asyncio.run(main())
"""

#: Запас на медленный окружение: фикс завершает shut-down за ~SPAWN_SETTLE_TIMEOUT_SECONDS.
_CHILD_TIMEOUT_SECONDS = 45


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _pending_tasks() -> list[asyncio.Task[None]]:
    return [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]


def _detector_temp_dirs() -> set[str]:
    return {name for name in os.listdir(tempfile.gettempdir()) if name.startswith("ai-detector-")}


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    """Локальный git-репозиторий без ни одного поддерживаемого файла (только изображение)."""
    src = tmp_path / "images-only"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.name", "student")
    _git(src, "config", "user.email", "student@example.com")
    (src / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR binary")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "только изображения")
    return src


def test_shutdown_with_in_flight_git_spawn_exits(local_repo: Path) -> None:
    """``asyncio.run`` с вполёте запуском git и синхронно падающим соседом завершается (регрессия зависания).

    До фикса CPython shut-down зависал навсегда (внутренняя задача
    ``_connect_pipes`` отменялась раньше подключения пайпов, и отменённая
    задача запуска не могла завершиться). Тест детерминирован: failer падает
    синхронно на первом шаге, loop останавливается ровно между Popen git и
    подключением пайпов.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT, str(local_repo)],
            capture_output=True,
            text=True,
            timeout=_CHILD_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "Дочерний процесс завис в shut-down asyncio.run "
            f"(>{_CHILD_TIMEOUT_SECONDS} c) — зависание CPython-орфана вернулось: "
            f"stdout={exc.stdout!r} stderr={exc.stderr!r}"
        )
    assert completed.returncode == 0, (
        f"dочерний процесс завершился кодом {completed.returncode}: "
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    assert "clean-exit" in completed.stdout


async def test_analyze_failure_mid_extract_cleans_temp_and_leaves_no_orphans(local_repo: Path) -> None:
    """``analyze()`` без поддерживаемых файлов: CodeAggregationError, temp чист, pending-задач нет."""
    service = AIDetectionService(AsyncOpenAI(base_url="http://127.0.0.1:1/v1", api_key="not-set"))
    before = _detector_temp_dirs()

    with pytest.raises(CodeAggregationError, match="no supported source files"):
        await service.analyze(TASK_CRITERIA, str(local_repo))

    assert _detector_temp_dirs() == before
    # Соседняя (git) ветка продолжает работу до естественного завершения —
    # даём loop реальное время её дождаться (Popen + git + EOF пайпов).
    await asyncio.sleep(0.5)
    assert _pending_tasks() == [], "сбой агрегатора не должен оставлять висящих задач в loop"
