"""Юнит-тесты LLMJudge: Structured Output через AsyncOpenAI, temperature=0, ретраи, тип ошибки (FR-008, FR-012).

Подмена: AsyncOpenAI (SimpleNamespace-фейк beta.chat.completions.parse), asyncio.sleep
(реальные экспоненциальные ожидания между ретраями убраны).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)

from ai_detector import llm_judge as llm_judge_module
from ai_detector.llm_judge import LLMJudge
from ai_detector.utils.exceptions import LLMJudgementError
from common.models import AIAssessmentResult, CommitInfo

REQUEST = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")
COMMIT = CommitInfo(
    hash="ab12" * 10,
    author="student",
    date="2026-03-01T14:22:05+03:00",
    message="первый коммит",
)
FULL_CODE = "--- FILE: lru.py ---\nclass LRUCache:\n    pass\n--- END FILE ---"


def make_result(**overrides: object) -> AIAssessmentResult:
    base: dict[str, object] = {
        "status": "green",
        "confidence": 0.9,
        "reasoning": "Постепенная история коммитов, осмысленные имена и естественные комментарии",
        "ai_indicators": [],
        "human_indicators": ["осмысленные сообщения коммитов"],
    }
    base.update(overrides)
    return AIAssessmentResult(**base)


def make_response(parsed: AIAssessmentResult | None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, content="сырой текст"))])


def make_client(parse: object) -> SimpleNamespace:
    """Фейк AsyncOpenAI: client.beta.chat.completions.parse(**kwargs)."""
    return SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))))


@pytest.fixture
def instant_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает реальные экспоненциальные ожидания между ретраями (asyncio.sleep → мгновенно)."""

    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)


async def test_happy_path_uses_parse_contract_params(instant_sleep: None) -> None:
    """FR-008: parse() с temperature=0, response_format=модель, system+user, данные целиком."""
    calls: list[dict[str, object]] = []

    async def fake_parse(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return make_response(make_result())

    judge = LLMJudge(make_client(fake_parse))  # type: ignore[arg-type]
    result = await judge.evaluate("Критерий: O(1)", ["lru.py"], [COMMIT], FULL_CODE)

    assert result.status == "green"
    (call,) = calls
    assert call["temperature"] == 0
    assert call["response_format"] is AIAssessmentResult
    assert call["model"] == llm_judge_module.DEFAULT_LLM_MODEL
    system, user = call["messages"]
    assert system["role"] == "system"
    assert "КРИТЕРИИ ВЕРДИКТА" in system["content"]
    assert "task_compliance_score" in system["content"]  # запрет поля прямо в промпте
    assert user["role"] == "user"
    assert "Критерий: O(1)" in user["content"]
    assert "lru.py" in user["content"]
    assert "ab12ab1 | 2026-03-01T14:22:05+03:00 | student | первый коммит" in user["content"]
    assert FULL_CODE in user["content"]  # весь код целиком, без усечения


async def test_result_is_exactly_parsed_field(instant_sleep: None) -> None:
    """Результат — ТОЛЬКО сообщение.parsed (identity с объектом модели)."""
    parsed = make_result(status="red")

    async def fake_parse(**kwargs: object) -> SimpleNamespace:
        return make_response(parsed)

    result = await LLMJudge(make_client(fake_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert result is parsed


async def test_model_from_env_var(instant_sleep: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель берётся из AI_DETECTOR_LLM_MODEL, иначе DEFAULT_LLM_MODEL."""
    monkeypatch.setenv("AI_DETECTOR_LLM_MODEL", "my-local-model")
    calls: list[dict[str, object]] = []

    async def fake_parse(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return make_response(make_result())

    await LLMJudge(make_client(fake_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert calls[0]["model"] == "my-local-model"


async def test_transient_5xx_retried_then_success(instant_sleep: None) -> None:
    """5xx два раза, затем успех → 3 вызова parse, вердикт получен."""
    attempts = 0

    async def flaky_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise APIStatusError("внутренняя ошибка", response=httpx.Response(500, request=REQUEST), body=None)
        return make_response(make_result())

    result = await LLMJudge(make_client(flaky_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert result.status == "green"
    assert attempts == 3


@pytest.mark.parametrize(
    "exception",
    [
        APIStatusError("упало", response=httpx.Response(502, request=REQUEST), body=None),
        APITimeoutError(request=REQUEST),
        APIConnectionError(request=REQUEST),
        RateLimitError("лимит", response=httpx.Response(429, request=REQUEST), body=None),
    ],
    ids=["5xx", "timeout", "connection", "rate-limit"],
)
async def test_transient_exceptions_retried_three_times(instant_sleep: None, exception: Exception) -> None:
    """Временные ошибки (5xx/timeout/соединение/429) → ровно 3 попытки, затем LLMJudgementError."""
    attempts = 0

    async def dead_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        raise exception

    with pytest.raises(LLMJudgementError) as exc_info:
        await LLMJudge(make_client(dead_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert attempts == 3
    assert "исчерпан" in str(exc_info.value)


async def test_parsed_none_retried_then_judgement_error(instant_sleep: None) -> None:
    """parse() вернул None → ретраи, после 3 попыток LLMJudgementError."""
    attempts = 0

    async def unparsed_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        return make_response(None)

    with pytest.raises(LLMJudgementError):
        await LLMJudge(make_client(unparsed_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert attempts == 3


async def test_not_found_not_retried(instant_sleep: None) -> None:
    """404 (нет модели) → НЕ ретраи, немедленный LLMJudgementError."""
    attempts = 0

    async def nf_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        raise NotFoundError("модель не найдена", response=httpx.Response(404, request=REQUEST), body=None)

    with pytest.raises(LLMJudgementError):
        await LLMJudge(make_client(nf_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert attempts == 1


async def test_context_overflow_400_not_retried(instant_sleep: None) -> None:
    """Переполнение контекста (400) → без ретраев, LLMJudgementError про вместимость."""
    attempts = 0

    async def overflow_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        raise BadRequestError(
            "This model's maximum context length is 8192 tokens",
            response=httpx.Response(400, request=REQUEST),
            body=None,
        )

    with pytest.raises(LLMJudgementError) as exc_info:
        await LLMJudge(make_client(overflow_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert attempts == 1
    assert "вместимость" in str(exc_info.value)


async def test_exhausted_error_is_plain_llm_judgement_error(instant_sleep: None) -> None:
    """На границе — именно LLMJudgementError (не служебный подтип)."""
    attempts = 0

    async def dead_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        raise APIStatusError("упало", response=httpx.Response(500, request=REQUEST), body=None)

    with pytest.raises(LLMJudgementError) as exc_info:
        await LLMJudge(make_client(dead_parse)).evaluate("к", [], [], "код")  # type: ignore[arg-type]
    assert type(exc_info.value) is LLMJudgementError
    assert "исчерпан" in str(exc_info.value)


async def test_empty_commit_history_renders_empty_prompt_section(instant_sleep: None) -> None:
    """Дегенеративный случай: история из 0 не-merge коммитов — секция в промпте присутствует, но пуста."""
    calls: list[dict[str, object]] = []

    async def fake_parse(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return make_response(make_result())

    await LLMJudge(make_client(fake_parse)).evaluate("к", ["lru.py"], [], FULL_CODE)  # type: ignore[arg-type]

    (call,) = calls
    messages = call["messages"]
    user = messages[1]
    content = str(user["content"])
    assert "- История коммитов: \n" in content  # секция на месте, значение пустое
    assert FULL_CODE in content  # код при этом передаётся целиком
