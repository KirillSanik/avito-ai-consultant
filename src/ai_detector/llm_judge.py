"""Оценка локальной LLM через OpenAI-совместимый Structured Output (FR-008, FR-012).

Ретраи и классификация ошибок — единый слой ``common.llm.call_with_resilience``
(3 попытки на модель, экспоненциальный бэкофф, 404 → смена модели). Результат
читается ТОЛЬКО из ``response.choices[0].message.parsed`` — raw-текст ответа
не интерпретируется (конституция §3). Устойчивые ошибки (404, переполнение
контекста 400) — немедленный ``LLMJudgementError`` без повторов.
"""

from __future__ import annotations

import logging
import os
import time

from openai import APIStatusError, AsyncOpenAI

from common.llm import (
    LLMRequestError,
    LLMResilienceError,
    LLMTransientError,
    call_with_resilience,
    is_model_unavailable,
)
from common.models import AIAssessmentResult, CommitInfo
from common.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, format_commit_history, format_file_tree

from .utils.exceptions import LLMJudgementError

logger = logging.getLogger(__name__)

#: Модель по умолчанию, если не задан ``AI_DETECTOR_LLM_MODEL`` (заглушка для локального сервера).
DEFAULT_LLM_MODEL = "local-model"


class LLMJudge:
    """Один Structured Output-запрос к локальной LLM; вердикт — объект ``AIAssessmentResult``."""

    MAX_ATTEMPTS = 3

    def __init__(self, client: AsyncOpenAI, model: str | None = None) -> None:
        self._client = client
        # Окружение читается при каждом обращении (сохранено поведение прежнего
        # common.config.llm_model; кешированные Settings не подходят).
        self._model = model or os.getenv("AI_DETECTOR_LLM_MODEL") or DEFAULT_LLM_MODEL

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
            result = await call_with_resilience(
                lambda model: self._parse_once(model, user_prompt),
                (self._model,),
                max_attempts=self.MAX_ATTEMPTS,
                inter_request_delay=0.0,
            )
        except LLMRequestError as exc:
            # Фатальный сбой без повторов (прочие статусы; переполнение контекста).
            logger.error("LLM-оценка не удалась за %.3f с: %s", time.perf_counter() - evaluate_started, exc)
            raise LLMJudgementError(str(exc)) from exc
        except LLMResilienceError as exc:
            logger.error("LLM-оценка не удалась за %.3f с: %s", time.perf_counter() - evaluate_started, exc)
            last_error = exc.last_error
            if last_error is not None and is_model_unavailable(last_error):
                raise LLMJudgementError(
                    f"LLM: модель «{self._model}» не найдена (404); проверьте AI_DETECTOR_LLM_MODEL ({last_error})"
                ) from exc
            detail = str(last_error) if last_error is not None else str(exc)
            raise LLMJudgementError(f"{detail} Лимит повторов исчерпан: {self.MAX_ATTEMPTS} попыток.") from exc
        logger.info("LLM-запрос выполнен за %.3f с", time.perf_counter() - evaluate_started)
        return result

    async def _parse_once(self, model: str, user_prompt: str) -> AIAssessmentResult:
        """Один запрос ``beta.chat.completions.parse`` с контрактом исключений."""
        attempt_started = time.perf_counter()
        logger.debug("LLM-запрос к модели «%s»…", model)
        try:
            response = await self._client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format=AIAssessmentResult,
            )
        except APIStatusError as exc:
            # Переполнение контекста — фатальная ошибка с особым сообщением (без повторов):
            # усечение кода запрещено (FR-004).
            if exc.status_code == 400 and "context" in str(exc).lower():
                logger.error("LLM-запрос: переполнение контекста (400)")
                raise LLMRequestError(
                    "LLM: объём данных превышает вместимость контекста модели; "
                    "усечение кода запрещено (FR-004)"
                ) from exc
            raise
        parsed = response.choices[0].message.parsed
        if parsed is None:
            logger.error("LLM-запрос: parsed=None после %.3f с", time.perf_counter() - attempt_started)
            raise LLMTransientError("LLM не вернула структурированное решение (parsed=None)")
        logger.debug("LLM-запрос: успешная попытка за %.3f с", time.perf_counter() - attempt_started)
        return parsed  # type: ignore[return-value]  # SDK типизировал parsed как Any; контракт — pydantic-объект
