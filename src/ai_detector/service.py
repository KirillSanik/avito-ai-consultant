"""Оркестрация пайплайна: clone → (git-метаданные ∥ полный код) → LLM-вердикт (FR-001, FR-006, FR-007)."""

from __future__ import annotations

import asyncio
import logging
import time

from openai import AsyncOpenAI

from .code_aggregator import LocalCodeAggregator
from .git_metadata import GitMetadataExtractor
from .llm_judge import LLMJudge
from .repo_cloner import RepoCloner
from .utils.models import AIAssessmentResult

logger = logging.getLogger(__name__)


class AIDetectionService:
    """Фасад модуля: один вызов ``analyze()`` — полный анализ репозитория.

    Конструктор — чистая сборка подсистем без I/O и без чтения окружения
    (SRP, DI): окружение читается только ``LLMJudge`` (имя модели) и
    ``RepoCloner`` (токен приватных репозиториев, US2).
    """

    def __init__(self, llm_client: AsyncOpenAI) -> None:
        self._cloner = RepoCloner()
        self._extractor = GitMetadataExtractor()
        self._aggregator = LocalCodeAggregator()
        self._judge = LLMJudge(llm_client)

    async def analyze(self, task_criteria: str, repo_url: str) -> AIAssessmentResult:
        """Полный анализ: временный клон → параллельный сбор данных → Structured Output-вердикт.

        Временная копия репозитория гарантированно удаляется до возврата
        (включая исключения и отмены) — FR-010, SC-004.
        """
        total_started = time.perf_counter()
        logger.info("Анализ начат: клонирование репозитория…")
        clone_started = time.perf_counter()
        async with self._cloner.clone(repo_url) as repo_path:
            logger.info(
                "Клонирование завершено за %.3f с — сбор метаданных и кода параллельно…",
                time.perf_counter() - clone_started,
            )
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
        result = await self._judge.evaluate(task_criteria, file_tree, commits, full_code)
        logger.info(
            "LLM-оценка завершена за %.3f с; общее время анализа: %.3f с; вердикт: %s (уверенность %.2f)",
            time.perf_counter() - judge_started,
            time.perf_counter() - total_started,
            result.status,
            result.confidence,
        )
        return result
