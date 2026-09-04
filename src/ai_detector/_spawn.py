"""Запуск git CLI, устойчивый к отмене вызывающей задачи.

Бихевиор CPython asyncio (наблюдено на 3.10–3.13.3): ``asyncio.create_subprocess_exec``
создаёт внутреннюю задачу event loop ``BaseSubprocessTransport._connect_pipes``,
которая подключает пайпы процесса. При отмене задачи-запускающего в окне между
созданием процесса и подключением пайпов CPython проходит «наивный» путь
отмены (``transp.close(); await transp._wait()``), а ``_wait()`` разрешается
только через ``_try_finish()`` — тот требует, чтобы **все пайпы были
подключены и отключены**. Если при этом задача ``_connect_pipes`` отменена
раньше, чем успела подключиться (так происходит при shut-down ``asyncio.run``:
``_cancel_all_tasks`` отменяет **все** pending-задачи разом, включая внутреннюю
``_connect_pipes``), пайпы так и остаются в ``None`` — ``_wait()`` никогда не
разрешается, ``_cancel_all_tasks`` ждёт вечно, и процесс зависает **без
исключения**. Второй ``cancel()`` задачи-запускающего разрывает тупик
(отменяет exit-waiter внутри ``_wait()``).

Обход состоит из двух частей:

1. запуск git идёт в отдельной задаче; если вызывающий отменён во время
   запуска, мы даём задаче запуска дойти до завершённого состояния
   (убив процесс при необходимости) и только затем пробрасываем
   ``CancelledError`` — в loop не остаётся осиротевших внутренних задач;
2. если после отмены задача запуска всё же зависла в ``transp._wait()``
   (сценарий из преамбулы), по истечении короткого окна ожидания мы
   отменяем её второй раз — это гарантирует завершение shut-down.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

__all__ = ["spawn_git"]

#: Сколько секунд дожидаться завершения задачи запуска после отмены.
#: Здоровый запуск оседает за десятки миллисекунд (kill + waitpid + EOF
#: пайпов). Если не оседает — задача зависла в ``transp._wait()`` CPython,
#: и срабатывает второй ``cancel()`` (см. модульную преамбулу).
SPAWN_SETTLE_TIMEOUT_SECONDS = 2.0

#: Сильные ссылки на задачи «сборщика» — event loop держит на них лишь слабые ссылки.
_REAPERS: set[asyncio.Task[None]] = set()


async def spawn_git(*argv: str) -> asyncio.subprocess.Process:
    """Запускает команду git (полный argv) с пайпами stdout/stderr.

    Отмена-безопасно: отмена вызывающей задачи не оставляет ни осиротевших
    внутренних задач event loop, ни запущенного git-процесса, и не
    зависает в shut-down ``asyncio.run``. Сбои запуска (например, git CLI
    недоступен) пробрасываются как есть — их обрабатывает вызывающий
    (доменная иерархия ``AIDetectionError``, FR-013).
    """
    spawn_task = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    )
    try:
        return await asyncio.shield(spawn_task)
    except asyncio.CancelledError:
        process: asyncio.subprocess.Process | None
        try:
            process = await _settle_spawn_task(spawn_task)
        except asyncio.CancelledError:
            # Повторная отмена во время ожидания: синхронно остановливаем
            # запуск, а «сборщик» добирает остаток (он не входит в срез
            # ``_cancel_all_tasks`` и доживёт до конца shut-down).
            if not spawn_task.done():
                spawn_task.cancel()
            elif not spawn_task.cancelled():
                with suppress(Exception):
                    spawn_task.result().kill()
            reaper = asyncio.get_running_loop().create_task(_reap_spawn_task(spawn_task))
            _REAPERS.add(reaper)
            reaper.add_done_callback(_REAPERS.discard)
            raise
        if process is not None:
            process.kill()
            try:
                await process.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        raise


async def _settle_spawn_task(
    spawn_task: asyncio.Task[asyncio.subprocess.Process],
) -> asyncio.subprocess.Process | None:
    """Дожидается оседания задачи запуска после отмены вызывающего.

    Возвращает запущенный процесс, если запуск завершился успешно (вызывающий
    сам его убивает); ``None``, если запуск не дошёл до процесса либо сбой
    запуска проигрывает отмене вызывающего.
    """
    try:
        await asyncio.wait({spawn_task}, timeout=SPAWN_SETTLE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    if not spawn_task.done():
        # Наивный путь отмены CPython завис в ``transp._wait()``: внутренняя
        # задача ``_connect_pipes`` отменена раньше подключения пайпов, и
        # exit-waiter никогда не разрешится. Второй ``cancel()`` отменяет
        # exit-waiter и освобождает задачу запуска (см. модульную преамбулу).
        spawn_task.cancel()
        with suppress(BaseException):
            await asyncio.shield(spawn_task)
        return None
    if spawn_task.cancelled():
        return None
    try:
        return spawn_task.result()
    except Exception:
        # Сбой запуска (например, нет git CLI): вызывающий и так отменён,
        # его отмена имеет приоритет — доменную ошибку сообщит shut-down.
        return None


async def _reap_spawn_task(spawn_task: asyncio.Task[asyncio.subprocess.Process]) -> None:
    """«Сборщик»: доводит задачу запуска до завершённого состояния.

    Вызывается при повторной отмене, когда основная ветка уже не может
    дожидаться. Гарантирует, что задача запуска не останется pending
    (иначе shut-down ``asyncio.run`` зависнет) и процесс git не останется
    живым.
    """
    try:
        process = await _settle_spawn_task(spawn_task)
    except BaseException:
        return
    if process is not None:
        process.kill()
        with suppress(BaseException):
            await asyncio.wait_for(process.wait(), timeout=SPAWN_SETTLE_TIMEOUT_SECONDS)
