"""Оркестрация анализа: (git-метаданные ∥ полный код) → LLM-вердикт (FR-001, FR-006, FR-007).

Клонирование не входит в метод оценки: ``analyze_from_path`` принимает
**готовый** локальный клон — API-пайплайн клонирует репозиторий ровно один
раз в ``core.pipeline`` (ТЗ §5.1). ``analyze`` — обёртка обратной
совместимости прежнего API: клон (``RepoCloner``) → ``analyze_from_path`` →
гарантированное удаление temp-каталога (FR-010, SC-004).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from openai import AsyncOpenAI

from common.models import AIAssessmentResult, TaskCriteria

from .code_aggregator import LocalCodeAggregator
from .git_metadata import GitMetadataExtractor
from .llm_judge import LLMJudge
from .repo_cloner import RepoCloner

logger = logging.getLogger(__name__)


class AIDetectionService:
    """Фасад модуля: один вызов ``analyze_from_path()`` — полный анализ локального клона.

    Конструктор — чистая сборка подсистем без I/O и без чтения окружения
    (SRP, DI): окружение читает только ``LLMJudge`` (имя модели).
    """

    def __init__(self, llm_client: AsyncOpenAI) -> None:
        self._cloner = RepoCloner()
        self._extractor = GitMetadataExtractor()
        self._aggregator = LocalCodeAggregator()
        self._judge = LLMJudge(llm_client)

    async def analyze(self, task_criteria: str | TaskCriteria, repo_url: str) -> AIAssessmentResult:
        """Полный анализ по URL (обратная совместимость): временный клон → ``analyze_from_path``.

        Временная копия репозитория гарантированно удаляется до возврата
        (включая исключения и отмены) — FR-010, SC-004.
        """
        criteria = (
            task_criteria
            if isinstance(task_criteria, TaskCriteria)
            else TaskCriteria(task_id="review", text=task_criteria)
        )
        logger.info("Анализ начат: клонирование репозитория…")
        async with self._cloner.clone(repo_url) as repo_path:
            return await self.analyze_from_path(criteria, repo_path)

    async def analyze_from_path(self, task_criteria: TaskCriteria, repo_path: Path) -> AIAssessmentResult:
        """Анализ готового локального клона: параллельный сбор данных → Structured Output-вердикт.

        Клонирование и парсинг условия не выполняются (ТЗ §5.1, пункт 3):
        на входе — путь к локальному клону и распарсенное ``TaskCriteria``.
        """
        total_started = time.perf_counter()
        logger.info("Сбор метаданных и кода параллельно…")
        metadata_task = asyncio.create_task(self._extractor.extract(repo_path))
        code_task = asyncio.create_task(self._aggregator.aggregate(repo_path))
        gather_started = time.perf_counter()
        try:
            (commits, file_tree), full_code = await asyncio.gather(metadata_task, code_task)
        except BaseException:
            logger.error("Сбор данных не удался, отмена параллельных задач")
            # Без отмены «собрата» он продолжил бы читать файлы после выхода
            # из контекста клона (temp-каталог уже удалён) — гонка и
            # «exception was never retrieved» в event loop.
            for task in (metadata_task, code_task):
                task.cancel()
            await asyncio.gather(metadata_task, code_task, return_exceptions=True)
            raise
        logger.info(
            "Сбор данных завершён за %.3f с: коммитов=%d, файлов=%d, объём кода=%d символов",
            time.perf_counter() - gather_started,
            len(commits),
            len(file_tree),
            len(full_code),
        )
        logger.info("LLM-оценка запущена…")
        judge_started = time.perf_counter()
        result = await self._judge.evaluate(task_criteria.text, file_tree, commits, full_code)
        logger.info(
            "LLM-оценка завершена за %.3f с; общее время анализа: %.3f с; вердикт: %s (уверенность %.2f)",
            time.perf_counter() - judge_started,
            time.perf_counter() - total_started,
            result.status,
            result.confidence,
        )
        return result
