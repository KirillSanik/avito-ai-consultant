"""Единый LLM-слой: классификация ошибок, ретраи, fallback по цепочке моделей.

Слой-обёртка для обоих модулей (``ai_detector`` и ``homework_reviewer``):
вызывающий передаёт асинхронную фабрику запроса ``coro_factory(model) -> T``
(внутри — прямой вызов ``AsyncOpenAI.beta.chat.completions.parse`` или
instructor ``chat.completions.create``), а слой отвечает за устойчивость:

- **ретраи** временных сбоев: 429, 402, таймауты, ошибки соединения,
  серверные 5xx, неполный/невалидированный вывод модели
  (``IncompleteOutputException``, ``InstructorRetryException``) —
  до ``max_attempts`` попыток на модель с экспоненциальной задержкой;
- **fallback**: 404 (модель недоступна) — немедленный переход к следующей
  модели ``model_chain``;
- **фатальные ошибки** (прочие статусы) — немедленный ``LLMRequestError``;
- исчерпание повторов/цепочки — ``LLMResilienceError`` с последней ошибкой.

Классификаторы ``is_retryable_error`` / ``is_model_unavailable`` перенесены
из ``GradingEngine``; поведение повторов — из ``LLMJudge`` (tenacity) и
петли ``GradingEngine``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from instructor.core import IncompleteOutputException, InstructorRetryException
from openai import APIConnectionError, APITimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Бесплатные модели OpenRouter — резервная цепочка ``Settings.model_chain``.
OPENROUTER_FREE_MODELS: tuple[str, ...] = (
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "openrouter/free",
)

#: Статусы, eligible для повтора (кроме 404 — он уходит в fallback-цепочку).
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({402, 429, 500, 502, 503, 504})

#: Маркеры сбоев в тексте ошибки (OpenRouter free-tier), по которым повтор допустим.
_RETRYABLE_MESSAGE_MARKERS: tuple[str, ...] = ("in_flight_budget_exhausted", "rate limit", "429")


class LLMError(Exception):
    """Базовое исключение единого LLM-слоя."""


class LLMTransientError(LLMError):
    """Временный сбой LLM (таймаут/соединение/429/402/5xx/невалидный вывод), eligible для повтора."""


class LLMModelUnavailableError(LLMError):
    """Модель недоступна (404): требуется переход к следующей модели цепочки."""


class LLMRequestError(LLMError):
    """Фатальная ошибка запроса (прочие статусы): повтор и fallback бессмысленны."""


class LLMResilienceError(LLMError):
    """Исчерпаны повторы на модели и/или вся цепочка моделей."""

    def __init__(self, message: str, last_error: BaseException | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


def is_retryable_error(error: BaseException) -> bool:
    """Временный сбой, eligible для повтора: 429/402/5xx, таймаут, соединение, неполный вывод.

    Проходит по цепочке ``__cause__``/``__context__`` (instructor/openai оборачивают
    нижележащие ошибки), затем смотрит маркеры в тексте сообщения.
    """
    current: BaseException | None = error
    while current is not None:
        status_code = getattr(current, "status_code", None)
        if (
            status_code in _RETRYABLE_STATUS_CODES
            or isinstance(
                current,
                (APIConnectionError, APITimeoutError, IncompleteOutputException, InstructorRetryException),
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    message = str(error).lower()
    return any(marker in message for marker in _RETRYABLE_MESSAGE_MARKERS)


def is_model_unavailable(error: BaseException) -> bool:
    """Модель/эндпоинт не найден (404): по статусу в цепочке ошибок или маркерам в тексте."""
    current: BaseException | None = error
    while current is not None:
        if getattr(current, "status_code", None) == 404:
            return True
        current = current.__cause__ or current.__context__
    message = str(error).lower()
    return "error code: 404" in message or '"code": 404' in message


def _attempt_delay(attempt: int) -> float:
    """Экспоненциальная задержка перед попыткой ``attempt`` (1, 2, 3, …): 2^n, потолок 10 с."""
    return min(2**attempt, 10)


async def call_with_resilience(
    coro_factory: Callable[[str], Awaitable[T]],
    model_chain: Sequence[str],
    *,
    max_attempts: int = 3,
    inter_request_delay: float = 2.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """Выполняет LLM-запрос с ретраями и fallback по цепочке моделей.

    :param coro_factory: фабрика запроса; получает имя модели, возвращает результат
        (валидированный pydantic-объект) или бросает SDK/instructor-исключение.
    :param model_chain: упорядоченная цепочка моделей от предпочтительной к резервным.
    :param max_attempts: максимальное число попыток на одну модель.
    :param inter_request_delay: пауза между последовательными запросами
        (rate-limit бесплатных моделей OpenRouter).
    :param sleep: инъекция ожидания (тестируемость); ``None`` — ``asyncio.sleep``,
        разрешаемый в момент вызова (monkeypatch-тестируемость).

    :raises LLMRequestError: фатальная ошибка запроса (без повторов).
    :raises LLMResilienceError: повторы на модели и цепочка исчерпаны.
    """
    if sleep is None:
        sleep = asyncio.sleep
    last_error: BaseException | None = None
    request_sent = False
    for model_name in model_chain:
        for attempt in range(max_attempts):
            if attempt:
                await sleep(_attempt_delay(attempt))
            if request_sent:
                await sleep(inter_request_delay)
            request_sent = True
            logger.debug("LLM-запрос к модели «%s» (попытка %d/%d)…", model_name, attempt + 1, max_attempts)
            try:
                return await coro_factory(model_name)
            except LLMRequestError:
                raise
            except LLMTransientError as exc:
                last_error = exc
                logger.warning(
                    "Временный сбой LLM (модель %s, попытка %d/%d): %s", model_name, attempt + 1, max_attempts, exc
                )
            except Exception as exc:
                if is_model_unavailable(exc):
                    last_error = exc
                    logger.error("Модель «%s» недоступна (404), переход к следующей модели цепочки", model_name)
                    break
                if not is_retryable_error(exc):
                    raise LLMRequestError(f"LLM: ошибка запроса (модель «{model_name}»): {exc}") from exc
                last_error = exc
                logger.warning(
                    "Временный сбой LLM (модель %s, попытка %d/%d): %s", model_name, attempt + 1, max_attempts, exc
                )
        if last_error is None:
            continue
        if not is_model_unavailable(last_error):
            # Повторы исчерпаны и ошибка не «404» — цепочка дальше не поможет.
            raise LLMResilienceError(
                f"LLM: не удалось получить ответ после {max_attempts} попыток "
                f"(модель «{model_name}»): {last_error}",
                last_error,
            ) from last_error
        # 404: пробуем следующую модель цепочки.
    raise LLMResilienceError(
        f"LLM: все модели цепочки исчерпаны ({len(list(model_chain))} моделей): {last_error}", last_error
    ) from last_error
