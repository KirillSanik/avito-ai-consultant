"""Оркестрация пайплайна: clone → (git-метаданные ∥ полный код) → LLM-вердикт (FR-001, FR-006, FR-007)."""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from .code_aggregator import LocalCodeAggregator
from .git_metadata import GitMetadataExtractor
from .llm_judge import LLMJudge
from .repo_cloner import RepoCloner
from .utils.models import AIAssessmentResult


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
        async with self._cloner.clone(repo_url) as repo_path:
            metadata_task = asyncio.create_task(self._extractor.extract(repo_path))
            code_task = asyncio.create_task(self._aggregator.aggregate(repo_path))
            try:
                (commits, file_tree), full_code = await asyncio.gather(metadata_task, code_task)
            except BaseException:
                # Без отмены «собрата» он продолжил бы читать файлы после выхода
                # из контекста клона (temp-каталог уже удалён) — гонка и
                # «exception was never retrieved» в event loop.
                for task in (metadata_task, code_task):
                    task.cancel()
                await asyncio.gather(metadata_task, code_task, return_exceptions=True)
                raise
        return await self._judge.evaluate(task_criteria, file_tree, commits, full_code)
