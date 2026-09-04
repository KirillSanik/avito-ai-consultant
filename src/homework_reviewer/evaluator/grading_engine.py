"""Покритериальная LLM-оценка (async) на едином LLM-слое ``common.llm``.

Движок не создаёт клиентов, не читает окружение, не пишет в репозитории
отчётов и не выводит сообщения в консоль: логирование — через ``logging``,
исключения — доменная иерархия ``homework_reviewer.exceptions`` (CLI-фасад
остаётся рабочим через ``asyncio.run``).

Клонирование репозитория и парсинг условия не выполняются: на вход —
готовая ``SubmissionData`` (для CLI) или ``(TaskCriteria, repo_path)``
(для API, см. ``evaluate_from_path``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import instructor

from common.llm import LLMRequestError, LLMResilienceError, call_with_resilience
from common.models import Criterion, CriterionResult, EvaluationReport, SubmissionData, TaskCriteria, TaskRubric
from common.prompts import GRADING_SYSTEM_PROMPT, GRADING_USER_PROMPT_TEMPLATE
from common.settings import Settings, get_settings
from homework_reviewer.exceptions import EvaluationError
from homework_reviewer.parsers.submission_parser import SubmissionParser

logger = logging.getLogger(__name__)

#: Параметры LLM-запроса покритериальной оценки (сохранены из прежней реализации).
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RETRIES = 1


class GradingEngine:
    """Оценивает работу последовательно по критериям рубрики (strict per-criterion)."""

    def __init__(self, client: instructor.Instructor, settings: Settings | None = None) -> None:
        self._client = client
        self.settings = settings or get_settings()

    async def evaluate_from_path(
        self, task_criteria: TaskCriteria, repo_path: Path, submission_id: str | None = None
    ) -> EvaluationReport:
        """Оценка локального клона репозитория (API-режим): без клонирования и парсинга ТЗ.

        Код читается из ``repo_path`` через ``SubmissionParser`` (в отдельном
        потоке — синхронные парсеры файлов и HTTP-проверка ссылок), далее —
        стандартная покритериальная оценка по ``task_criteria.rubric``.
        """
        if task_criteria.rubric is None:
            raise EvaluationError("В TaskCriteria отсутствует рубрика (rubric) — условие не распарсено")
        parser = SubmissionParser(self.settings, task_criteria.task_id)
        submission = await asyncio.to_thread(
            parser.build_from_local_repository,
            repo_path,
            submission_id or repo_path.name,
            task_criteria.task_id,
        )
        return await self.evaluate_submission(task_criteria.rubric, submission)

    async def evaluate_criterion(
        self,
        criterion: Criterion,
        task_rubric: TaskRubric,
        submission_data: SubmissionData,
    ) -> CriterionResult:
        """Один критерий: structured output (instructor) с ретраями и fallback по цепочке моделей."""
        settings = self.settings
        file_tree = "\n".join(submission_data.file_tree) or (
            f"{submission_data.submission_id}.{submission_data.file_type}"
        )
        raw_text = settings.limit_input_text(submission_data.raw_text)
        full_instructions = settings.limit_input_text(task_rubric.full_instructions)
        excel_audit = (
            submission_data.excel_audit.model_dump_json(indent=2) if submission_data.excel_audit else "Нет"
        )
        resolved_links = "\n".join(link.model_dump_json() for link in submission_data.resolved_links) or "Нет"
        user_prompt = GRADING_USER_PROMPT_TEMPLATE.format(
            title=task_rubric.title,
            description=task_rubric.description,
            guidelines="\n".join(task_rubric.guidelines) or "Нет",
            constraints=task_rubric.constraints.model_dump_json(indent=2),
            full_instructions=full_instructions,
            criterion_id=criterion.name,
            criterion_name=criterion.name,
            max_points=criterion.max_points,
            criterion_description=criterion.description,
            submission_id=submission_data.submission_id,
            file_tree=file_tree,
            raw_text=raw_text,
            excel_audit=excel_audit,
            resolved_links=resolved_links,
        )

        try:
            result = await call_with_resilience(
                lambda model: self._instructor_create(model, user_prompt),
                settings.model_chain,
            )
        except (LLMRequestError, LLMResilienceError) as exc:
            logger.error("Ошибка LLM-провайдера: %s", exc)
            raise EvaluationError(f"Не удалось оценить критерий «{criterion.name}».") from exc

        assigned_score = min(max(float(result.assigned_score), 0.0), float(criterion.max_points))
        return result.model_copy(
            update={
                "criterion_id": criterion.name,
                "criterion_name": criterion.name,
                "assigned_score": assigned_score,
                "max_points": float(criterion.max_points),
            }
        )

    async def _instructor_create(self, model: str, user_prompt: str) -> CriterionResult:
        """Один запрос instructor (JSON-режим) к указанной модели; ошибки пробрасываются как есть."""
        settings = self.settings
        request_options: dict[str, object] = {
            "max_tokens": settings.llm_max_tokens,
            "response_model": CriterionResult,
            "max_retries": DEFAULT_MAX_RETRIES,
            "timeout": DEFAULT_TIMEOUT_SECONDS,
            "messages": [
                {"role": "system", "content": GRADING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        if settings.chat_extra_body:
            request_options["extra_body"] = settings.chat_extra_body
        return await self._client.chat.completions.create(model=model, **request_options)

    async def evaluate_submission(self, rubric: TaskRubric, submission_data: SubmissionData) -> EvaluationReport:
        """Оценка всех критериев параллельно (LLM-вызовы независимы); в storage отчёт не сохраняется.

        Сбой одного критерия отменяет остальные (как в ``core.pipeline``) —
        частичный отчёт не возвращается.
        """
        criteria = list(rubric.criteria)
        logger.info("Параллельная оценка %d критериев…", len(criteria))

        async def _one(index: int, criterion: Criterion) -> CriterionResult:
            started = time.perf_counter()
            logger.info("Оценивается критерий %d/%d: %s", index, len(criteria), criterion.name)
            result = await self.evaluate_criterion(criterion, rubric, submission_data)
            logger.info("Критерий %d/%d оценён за %.1f с", index, len(criteria), time.perf_counter() - started)
            return result.model_copy(update={"criterion_id": f"criterion-{index}"})

        tasks = [asyncio.create_task(_one(i, c)) for i, c in enumerate(criteria, start=1)]
        try:
            criterion_results = list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        total_score = sum(result.assigned_score for result in criterion_results)
        max_total_score = sum(result.max_points for result in criterion_results)
        return EvaluationReport(
            task_id=rubric.task_id,
            submission_id=submission_data.submission_id,
            total_score=total_score,
            max_total_score=max_total_score,
            criterion_results=criterion_results,
            summary_feedback=self._build_summary_feedback(criterion_results, total_score, max_total_score),
        )

    @staticmethod
    def _build_summary_feedback(
        criterion_results: list[CriterionResult],
        total_score: float,
        max_total_score: float,
    ) -> str:
        if not criterion_results:
            return "В рубрике нет критериев для формирования итоговой обратной связи."
        score_line = f"Итог: {total_score:g} из {max_total_score:g} баллов."
        details = " ".join(
            f"{result.criterion_name}: {result.assigned_score:g}/{result.max_points:g}. {result.reasoning.strip()}"
            for result in criterion_results
        )
        return f"{score_line} {details}".strip()
