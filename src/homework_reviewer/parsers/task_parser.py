"""Тонкая обёртка над вынесенным в ``common.parsers`` разбором условия (CLI-совместимость).

Сами шаги — (а) извлечение текста без LLM и (б) LLM-структурирование в рубрику —
живут в общем слое: ``common.parsers.extract_task_text`` и
``common.parsers.parse_task_rubric``. Внутренние парсеры на этом этапе
дублирующую логику не содержат.
"""

from __future__ import annotations

from pathlib import Path

import instructor

from common.models import TaskRubric
from common.parsers import extract_task_text, parse_task_rubric
from common.settings import Settings, get_settings


class TaskParser:
    """Разбор файла с условием в ``TaskRubric`` (async): текст → LLM → regex-fallback."""

    def __init__(self, settings: Settings | None = None, client: instructor.Instructor | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def _get_client(self) -> instructor.Instructor:
        if self._client is None:
            from common.clients import get_openrouter_client

            self._client = get_openrouter_client(self.settings)
        return self._client

    def extract_text(self, path: str | Path) -> str:
        """Этап (а): извлечение текста из файла (без LLM)."""
        return extract_task_text(path)

    async def parse_task(self, pdf_path: str | Path, task_id: str) -> TaskRubric:
        """Полный разбор: извлечение текста + LLM-структурирование (один раз)."""
        full_text = extract_task_text(pdf_path)
        return await parse_task_rubric(full_text, task_id, client=self._get_client(), settings=self.settings)
