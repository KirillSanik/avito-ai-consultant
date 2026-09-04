"""Юнит-тесты единого LLM-слоя ``common.llm``: классификация, ретраи, fallback-цепочка.

Подмена: asyncio.sleep (инъекция через параметр ``sleep``) и фабрика запроса
(леймбда, поднимающая заранее поставленные SDK-исключения или возвращающая
валидированный результат).
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from instructor.core import IncompleteOutputException
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

from common.llm import (
    LLMRequestError,
    LLMResilienceError,
    call_with_resilience,
    is_model_unavailable,
    is_retryable_error,
)

REQUEST = httpx.Request("POST", "http://openrouter.test/v1/chat/completions")
CHAIN = ("model-a", "model-b")


def make_status_error(status_code: int, message: str = "сбой") -> APIStatusError:
    response = httpx.Response(status_code, request=REQUEST)
    if status_code == 400:
        return BadRequestError(f"{message} (code: {status_code})", response=response, body=None)
    if status_code == 404:
        return NotFoundError(f"{message} (code: {status_code})", response=response, body=None)
    if status_code == 429:
        return RateLimitError(f"{message} (code: {status_code})", response=response, body=None)
    if status_code == 503:
        # В openai SDK нет отдельного класса 503 — используем базовый APIStatusError.
        return APIStatusError(f"{message} (code: {status_code})", response=response, body=None)
    return InternalServerError(f"{message} (code: {status_code})", response=response, body=None)


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (make_status_error(429), True),
        (make_status_error(500), True),
        (make_status_error(502), True),
        (make_status_error(503), True),
        (make_status_error(504), True),
        (APIConnectionError(request=REQUEST), True),
        (APITimeoutError(request=REQUEST), True),
        (IncompleteOutputException("partial output"), True),
        (make_status_error(400, "context length exceeded"), False),
        (make_status_error(401), False),
        (make_status_error(404), False),
        (ValueError("обычная ошибка"), False),
    ],
    ids=str,
)
def test_is_retryable_error_classification(error: BaseException, expected: bool) -> None:
    assert is_retryable_error(error) is expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (make_status_error(404), True),
        (ValueError('модель не найдена "code": 404'), True),
        (make_status_error(429), False),
        (APIConnectionError(request=REQUEST), False),
    ],
    ids=str,
)
def test_is_model_unavailable_classification(error: BaseException, expected: bool) -> None:
    assert is_model_unavailable(error) is expected


async def test_success_on_first_attempt_returns_result() -> None:
    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        return "ok"

    sleep = SleepRecorder()
    result = await call_with_resilience(factory, CHAIN, sleep=sleep.sleep)
    assert result == "ok"
    assert calls == ["model-a"]
    assert sleep.delays == []


async def test_retryable_error_retried_then_succeeds() -> None:
    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise make_status_error(429, "rate limit exceeded")
        return "ok"

    sleep = SleepRecorder()
    result = await call_with_resilience(factory, CHAIN, max_attempts=3, sleep=sleep.sleep)
    assert result == "ok"
    assert calls == ["model-a", "model-a"]
    assert sleep.delays == [2.0, 2.0]  # бэкофф перед 2-й попыткой + пауза между запросами


async def test_not_found_switches_to_next_model_in_chain() -> None:
    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        if model == "model-a":
            raise make_status_error(404, "model not found")
        return "ok"

    sleep = SleepRecorder()
    result = await call_with_resilience(factory, CHAIN, sleep=sleep.sleep)
    assert result == "ok"
    assert calls == ["model-a", "model-b"]


async def test_fatal_error_raises_llm_request_error_without_retry() -> None:
    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        raise make_status_error(400, "bad request")

    sleep = SleepRecorder()
    with pytest.raises(LLMRequestError):
        await call_with_resilience(factory, CHAIN, sleep=sleep.sleep)
    assert calls == ["model-a"]  # без повторов и без смены модели
    assert sleep.delays == []


async def test_exhausted_attempts_raises_resilience_error_with_last_error() -> None:
    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        raise make_status_error(500, "внутренняя ошибка сервера")

    sleep = SleepRecorder()
    with pytest.raises(LLMResilienceError) as exc_info:
        await call_with_resilience(factory, CHAIN, max_attempts=2, sleep=sleep.sleep)
    assert calls == ["model-a", "model-a"]
    assert isinstance(exc_info.value.last_error, InternalServerError)
    assert "2 попыток" in str(exc_info.value)


async def test_all_models_unavailable_raises_resilience_error() -> None:
    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        raise make_status_error(404, "model not found")

    sleep = SleepRecorder()
    with pytest.raises(LLMResilienceError) as exc_info:
        await call_with_resilience(factory, CHAIN, sleep=sleep.sleep)
    assert calls == ["model-a", "model-b"]
    assert "все модели цепочки исчерпаны" in str(exc_info.value)
    assert exc_info.value.last_error is not None


async def test_wrapped_openai_error_is_classified_through_cause_chain() -> None:
    """instructor/openai оборачивают нижележащие ошибки — классификатор идёт по __cause__."""
    root = make_status_error(429, "rate limit")
    wrapper = RuntimeError("instructor: retry failed")
    wrapper.__cause__ = root

    calls: list[str] = []

    async def factory(model: str) -> str:
        calls.append(model)
        if len(calls) < 3:
            raise wrapper
        return "ok"

    sleep = SleepRecorder()
    result = await call_with_resilience(factory, CHAIN, max_attempts=3, sleep=sleep.sleep)
    assert result == "ok"
    assert len(calls) == 3


def test_llm_error_hierarchy_is_exception_only() -> None:
    """Иерархия слоя — только подклассы Exception (без Any в сигнатурах)."""
    assert issubclass(LLMRequestError, Exception)
    assert issubclass(LLMResilienceError, Exception)
    sentinel = LLMResilienceError("msg", SimpleNamespace(status_code=429))
    assert isinstance(sentinel.last_error, SimpleNamespace)
