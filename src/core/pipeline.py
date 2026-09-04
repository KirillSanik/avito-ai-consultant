"""Пайплайн: единая оркестрация детекции и ревью одного запроса (ТЗ §5.1).

Жизненный цикл ``Pipeline.run`` (каждый тяжёлый I/O-шаг — **строго один раз**):

1. **Парсинг условия** — общий слой ``common.parsers``: извлечение текста из
   ``task_file`` (без LLM, в отдельном потоке) и LLM-структурирование в
   ``TaskRubric``; результат маппится в общую модель ``TaskCriteria``.
2. **Клонирование** — ``core.repo_clone.clone_repo``: одна временная копия
   репозитория, путь возвращается, автоудаления нет.
3. **``asyncio.gather``** только финальных оценок:
   ``detector.analyze_from_path`` ∥ ``reviewer.evaluate_from_path`` —
   оба получают уже готовые ``TaskCriteria`` и ``repo_path``.
4. **Очистка** — ``shutil.rmtree`` temp-каталога в ``finally`` строго после
   завершения gather (успех, исключение, отмена); при сбое одной из задач
   вторая отменяется и дожидается.
5. **Агрегация** — ``ReviewResponse`` (общая схема ``common.models``).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import urlparse

import instructor

from common.clients import get_openrouter_client
from common.models import AIAssessmentResult, EvaluationReport, ReviewResponse, TaskCriteria
from common.parsers import extract_task_text, parse_task_rubric
from common.settings import Settings, get_settings
from core.repo_clone import clone_repo

logger = logging.getLogger(__name__)


class _Detector(Protocol):
    """Контракт исполнителя детекции: анализ готового локального клона."""

    async def analyze_from_path(self, task_criteria: TaskCriteria, repo_path: Path) -> AIAssessmentResult: ...


class _Reviewer(Protocol):
    """Контракт исполнителя ревью: оценка готового локального клона."""

    async def evaluate_from_path(
        self, task_criteria: TaskCriteria, repo_path: Path, submission_id: str | None = None
    ) -> EvaluationReport: ...


class Pipeline:
    """Управляет жизненным циклом обработки запроса ``POST /review``.

    Сервисы-исполнители передаются внедрением (DI): пайплайн не создаёт
    клиентов LLM и не читает окружение (кроме общих настроек).
    """

    def __init__(self, detector: _Detector, reviewer: _Reviewer, settings: Settings | None = None) -> None:
        self._detector = detector
        self._reviewer = reviewer
        self.settings = settings or get_settings()
        self._rubric_client: instructor.Instructor | None = None

    def _rubric_client(self) -> instructor.Instructor:
        """Lazy-фабрика instructor-клиента для разбора условия (один на процесс)."""
        if self._rubric_client is None:
            self._rubric_client = get_openrouter_client(self.settings)
        return self._rubric_client

    @staticmethod
    def _submission_id(repo_url: str) -> str:
        """Идентификатор сдачи: stem имени репозитория в URL (например, ``repo``)."""
        stem = PurePosixPath(urlparse(repo_url).path or repo_url).stem
        return stem or "submission"

    async def run(self, repo_url: str, task_file: str | Path) -> ReviewResponse:
        """Полная проверка: один парсинг + один клон → параллельные оценки → ответ."""
        task_file = Path(task_file)
        task_id = task_file.stem or "review"
        total_started = time.perf_counter()

        # 1. Парсинг условия — ровно один раз (ТЗ §5.1, пункт 1).
        parse_started = time.perf_counter()
        logger.info("Парсинг условия задачи начат: файл=%s, task_id=%s", task_file.name, task_id)
        full_text = await asyncio.to_thread(extract_task_text, task_file)
        rubric = await parse_task_rubric(full_text, task_id, client=self._rubric_client(), settings=self.settings)
        task_criteria = TaskCriteria(task_id=task_id, text=full_text, rubric=rubric)
        logger.info(
            "Парсинг условия завершён за %.3f с (символов=%d, критериев=%d)",
            time.perf_counter() - parse_started,
            len(full_text),
            len(rubric.criteria),
        )

        # 2. Клонирование — ровно один раз, без автоудаления (ТЗ §5.1, пункт 2).
        clone_started = time.perf_counter()
        repo_path = await clone_repo(repo_url)
        logger.info("Клонирование завершено за %.3f с: %s", time.perf_counter() - clone_started, repo_path)

        try:
            # 3. Параллельно — только финальные оценки по готовым входам (ТЗ §5.1, пункт 3).
            gather_started = time.perf_counter()
            detector_task = asyncio.create_task(self._detector.analyze_from_path(task_criteria, repo_path))
            reviewer_task = asyncio.create_task(
                self._reviewer.evaluate_from_path(task_criteria, repo_path, self._submission_id(repo_url))
            )
            try:
                ai_assessment, evaluation = await asyncio.gather(detector_task, reviewer_task)
            except BaseException:
                # Сбой одной из задач: отменить вторую и дождаться, чтобы не
                # оставалось задач, читающих удалённый temp-каталог (гонка).
                logger.error("Одна из оценок не удалась, отмена параллельной задачи")
                for task in (detector_task, reviewer_task):
                    task.cancel()
                await asyncio.gather(detector_task, reviewer_task, return_exceptions=True)
                raise
            logger.info("Оценки завершены за %.3f с", time.perf_counter() - gather_started)
        finally:
            # 4. Очистка строго после завершения gather (ТЗ §5.1, пункт 4):
            # успех, исключение или отмена — temp-каталог гарантированно удалён.
            cleanup_started = time.perf_counter()
            shutil.rmtree(repo_path.parent, ignore_errors=True)
            logger.info("Temp-каталог удалён за %.3f с", time.perf_counter() - cleanup_started)

        # 5. Агрегация результатов (ТЗ §5.1, пункт 5).
        logger.info(
            "Пайплайн завершён за %.3f с: вердикт=%s, итог=%.1f/%.1f",
            time.perf_counter() - total_started,
            ai_assessment.status,
            evaluation.total_score,
            evaluation.max_total_score,
        )
        return ReviewResponse(
            repo_url=repo_url,
            task_id=task_criteria.task_id,
            ai_assessment=ai_assessment,
            evaluation=evaluation,
        )
