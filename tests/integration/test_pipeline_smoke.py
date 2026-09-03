"""Интеграционный дым: полный пайплайн на реальном локальном git-репозитории (T018).

Сценарий (quickstart.md §4): фиксатурный репозиторий (`git init` + коммиты в `tmp_path`) +
реальный `git clone` локальным путём + мок `AsyncOpenAI` → `AIDetectionService.analyze`
возвращает полный `AIAssessmentResult`; после вызова temp-каталоги не остаются (SC-004).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_detector import AIAssessmentResult, AIDetectionService

TASK_CRITERIA = "Критерии: LRU-кэш с ограничением capacity, методами get/set/clear, без внешних зависимостей."

LRU_CODE_V1 = '''class LRUCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._order: list[int] = []
        self._items: dict[int, int] = {}

    def get(self, key: int) -> int:
        if key not in self._items:
            raise KeyError(key)
        self._order.remove(key)
        self._order.append(key)
        return self._items[key]

    def set(self, key: int, value: int) -> None:
        if key in self._items:
            self._order.remove(key)
        elif len(self._order) >= self.capacity:
            oldest = self._order.pop(0)
            del self._items[oldest]
        self._order.append(key)
        self._items[key] = value
'''

LRU_CODE_V2 = LRU_CODE_V1 + """
    def clear(self) -> None:
        self._order.clear()
        self._items.clear()
"""

README_TEXT = "# Домашнее задание\n\nРеализация LRU-кэша на Python.\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    """Локальный git-репозиторий с двумя коммитами (`.py` + `.md`)."""
    src = tmp_path / "source"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.name", "student")
    _git(src, "config", "user.email", "student@example.com")
    (src / "lru.py").write_text(LRU_CODE_V1, encoding="utf-8")
    (src / "README.md").write_text(README_TEXT, encoding="utf-8")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "Добавил LRU-кэш")
    (src / "lru.py").write_text(LRU_CODE_V2, encoding="utf-8")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "Добавил метод clear")
    return src


class FakeCompletions:
    """Мок `AsyncOpenAI.beta.chat.completions.parse`, фиксирующий аргументы вызова."""

    def __init__(self, parsed: AIAssessmentResult) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object):
        self.calls.append(kwargs)
        message = SimpleNamespace(parsed=self.parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _make_service(result: AIAssessmentResult) -> tuple[AIDetectionService, FakeCompletions]:
    completions = FakeCompletions(result)
    client = SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return AIDetectionService(client), completions


def _detector_temp_dirs() -> set[str]:
    return {name for name in os.listdir(tempfile.gettempdir()) if name.startswith("ai-detector-")}


def _user_prompt_of(completions: FakeCompletions) -> str:
    assert len(completions.calls) == 1
    call = completions.calls[0]
    messages = call["messages"]
    assert isinstance(messages, list) and len(messages) == 2
    second = messages[1]
    assert isinstance(second, dict)
    return str(second["content"])


async def test_full_pipeline_returns_result_and_leaves_no_temp_dirs(source_repo: Path) -> None:
    result_value = AIAssessmentResult(
        status="green",
        confidence=0.9,
        reasoning="Решение написано вручную: понятные коммиты, итеративная доработка.",
        ai_indicators=[],
        human_indicators=["Два осмысленных коммита", "Метод clear добавлен отдельным коммитом"],
    )
    service, completions = _make_service(result_value)
    before = _detector_temp_dirs()

    result = await service.analyze(TASK_CRITERIA, str(source_repo))

    assert result is result_value
    assert result.status == "green"
    prompt = _user_prompt_of(completions)
    # Критерии задания и структура репозитория (FR-007).
    assert TASK_CRITERIA in prompt
    assert "lru.py" in prompt
    assert "README.md" in prompt
    # Полный код с маркерами, без усечения (FR-004): версия из второго коммита.
    assert "--- FILE: lru.py ---" in prompt
    assert "--- END FILE ---" in prompt
    assert "def clear(self) -> None:" in prompt
    # История коммитов без merge-коммитов (FR-003).
    assert "student | Добавил LRU-кэш" in prompt
    assert "student | Добавил метод clear" in prompt
    # Временные каталоги не остались (SC-004).
    assert _detector_temp_dirs() == before
