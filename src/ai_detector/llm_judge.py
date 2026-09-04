"""Оценка локальной LLM через OpenAI-совместимый Structured Output с ретраями (FR-008, FR-012).

Результат читается ТОЛЬКО из ``response.choices[0].message.parsed`` —
raw-текст ответа не интерпретируется (конституция §3). Повторяются только
временные сбои (3 попытки, экспоненциальный бэкофф); устойчивые ошибки
(404, переполнение контекста 400) — немедленный ``LLMJudgementError``.
"""

from __future__ import annotations

import logging
import os
import time

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    NotFoundError,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .utils.exceptions import LLMJudgementError
from .utils.models import AIAssessmentResult, CommitInfo
from .utils.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, format_commit_history, format_file_tree

logger = logging.getLogger(__name__)

#: Модель по умолчанию, если не задан ``AI_DETECTOR_LLM_MODEL`` (заглушка для локального сервера).
DEFAULT_LLM_MODEL = "local-model"


class _TransientLLMError(LLMJudgementError):
    """Служебный (не экспортируется): временный сбой LLM, eligible для повтора."""


class LLMJudge:
    """Один Structured Output-запрос к локальной LLM; вердикт — объект ``AIAssessmentResult``."""

    MAX_ATTEMPTS = 3

    def __init__(self, client: AsyncOpenAI, model: str | None = None) -> None:
        self._client = client
        self._model = model or os.environ.get("AI_DETECTOR_LLM_MODEL") or DEFAULT_LLM_MODEL

    async def evaluate(
        self, task_criteria: str, file_tree: list[str], commits: list[CommitInfo], full_code: str
    ) -> AIAssessmentResult:
        """Полная оценка: критерии + метаданные репозитория + весь исходный код → вердикт."""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            task_criteria=task_criteria,
            file_tree=format_file_tree(file_tree),
            commit_history_formatted=format_commit_history(commits),
            full_code=full_code,
        )
        logger.debug(
            "LLM-оценка: промпт собран (символов=%d: коммитов=%d, файлов=%d, кода=%d)",
            len(user_prompt),
            len(commits),
            len(file_tree),
            len(full_code),
        )
        evaluate_started = time.perf_counter()
        try:
            result = await self._request(user_prompt)
        except _TransientLLMError as exc:
            logger.error("LLM-оценка не удалась за %.3f с: %s", time.perf_counter() - evaluate_started, exc)
            raise LLMJudgementError(f"{exc} Лимит повторов исчерпан: {self.MAX_ATTEMPTS} попыток.") from exc
        logger.info("LLM-запрос выполнен за %.3f с", time.perf_counter() - evaluate_started)
        return result

    @retry(
        retry=retry_if_exception_type(_TransientLLMError),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _request(self, user_prompt: str) -> AIAssessmentResult:
        """Один запрос ``beta.chat.completions.parse`` с контрактом исключений."""
        attempt_started = time.perf_counter()
        attempt_number = getattr(self._request.retry.statistics, "attempt_number", 1) if hasattr(self._request, "retry") else 1
        logger.debug("LLM-запрос к модели «%s» (попытка %d)…", self._model, attempt_number)
        try:
            response = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format=AIAssessmentResult,
            )
        except APITimeoutError as exc:
            logger.error("LLM-запрос: таймаут после %.3f с", time.perf_counter() - attempt_started)
            raise _TransientLLMError(f"LLM: таймаут запроса ({exc})") from exc
        except APIConnectionError as exc:
            logger.error("LLM-запрос: ошибка соединения после %.3f с", time.perf_counter() - attempt_started)
            raise _TransientLLMError(f"LLM: не удалось подключиться к локальному LLM-серверу ({exc})") from exc
        except RateLimitError as exc:
            logger.error("LLM-запрос: 429 после %.3f с", time.perf_counter() - attempt_started)
            raise _TransientLLMError(f"LLM: превышен лимит запросов ({exc})") from exc
        except NotFoundError as exc:
            logger.error("LLM-запрос: модель «%s» не найдена (404)", self._model)
            raise LLMJudgementError(
                f"LLM: модель «{self._model}» не найдена (404); проверьте AI_DETECTOR_LLM_MODEL ({exc})"
            ) from exc
        except APIStatusError as exc:
            logger.error("LLM-запрос: статус %d после %.3f с", exc.status_code, time.perf_counter() - attempt_started)
            if exc.status_code >= 500:
                raise _TransientLLMError(f"LLM: серверная ошибка ({exc.status_code})") from exc
            if exc.status_code == 400 and "context" in str(exc).lower():
                raise LLMJudgementError(
                    "LLM: объём данных превышает вместимость контекста модели; "
                    "усечение кода запрещено (FR-004)"
                ) from exc
            raise LLMJudgementError(f"LLM: ошибка запроса ({exc.status_code})") from exc
        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("LLM-запрос: parsed=None после %.3f с", time.perf_counter() - attempt_started)
            raise _TransientLLMError("LLM не вернула структурированное решение (parsed=None)")
        logger.debug("LLM-запрос: успешная попытка за %.3f с", time.perf_counter() - attempt_started)
        return parsed  # type: ignore[return-value]  # SDK типизировал parsed как Any; контракт — pydantic-объект
