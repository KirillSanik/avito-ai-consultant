"""Интеграционный дым: полный пайплайн на реальном локальном git-репозитории (T018, T026).

Сценарий (quickstart.md §4): фиксатурный репозиторий (`git init` + коммиты в `tmp_path`) +
реальный `git clone` локальным путём + мок `AsyncOpenAI` → `AIDetectionService.analyze`
возвращает полный `AIAssessmentResult`; после вызова temp-каталоги не остаются (SC-004).

Негативные сценарии (quickstart.md §6, T026): несуществующий URL → `RepoCloneError`;
репозиторий без поддерживаемого кода → `CodeAggregationError`; мёртвый LLM-порт
(`APIConnectionError`) → `LLMJudgementError` после ровно 3 повторов (SC-006).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from ai_detector import AIAssessmentResult, AIDetectionService, CodeAggregationError, LLMJudgementError, RepoCloneError

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


# ---------------------------------------------------------------------------
# Негативные сценарии (quickstart.md §6, T026)
# ---------------------------------------------------------------------------


def _default_result() -> AIAssessmentResult:
    return AIAssessmentResult(
        status="green",
        confidence=0.9,
        reasoning="причина",
        ai_indicators=[],
        human_indicators=[],
    )


async def test_nonexistent_repo_url_raises_repo_clone_error(tmp_path: Path) -> None:
    """quickstart §6: несуществующий URL → RepoCloneError с русским сообщением, без следов temp (FR-013, SC-004)."""
    service, _completions = _make_service(_default_result())
    before = _detector_temp_dirs()

    with pytest.raises(RepoCloneError) as exc_info:
        await service.analyze(TASK_CRITERIA, str(tmp_path / "does-not-exist"))

    assert "Не удалось" in str(exc_info.value)  # человекочитаемое сообщение на русском
    assert _detector_temp_dirs() == before  # следов клона не осталось


@pytest.fixture
def image_only_repo(tmp_path: Path) -> Path:
    """Локальный git-репозиторий без ни одного поддерживаемого файла (только изображение)."""
    src = tmp_path / "images-only"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.name", "student")
    _git(src, "config", "user.email", "student@example.com")
    (src / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR binary")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "только изображения")
    return src


async def test_repo_without_supported_code_raises_code_aggregation_error(image_only_repo: Path) -> None:
    """quickstart §6: репозиторий без поддерживаемого кода → CodeAggregationError «no supported source files»."""
    service, _completions = _make_service(_default_result())
    before = _detector_temp_dirs()

    with pytest.raises(CodeAggregationError, match="no supported source files"):
        await service.analyze(TASK_CRITERIA, str(image_only_repo))

    assert _detector_temp_dirs() == before  # клон удалён даже при сбое агрегации


async def test_dead_llm_server_raises_judgement_error_after_three_retries(
    source_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """quickstart §6: мёртвый LLM-порт (APIConnectionError) → LLMJudgementError после ровно 3 повторов (SC-006)."""

    async def _sleep(_delay: float) -> None:
        return None  # реальные экспоненциальные задержки между ретраями убираем

    monkeypatch.setattr(asyncio, "sleep", _sleep)

    request = httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions")
    attempts = 0

    async def dead_parse(**_kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        raise APIConnectionError(request=request)

    client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=dead_parse)))
    )
    service = AIDetectionService(client)  # type: ignore[arg-type]
    before = _detector_temp_dirs()

    with pytest.raises(LLMJudgementError) as exc_info:
        await service.analyze(TASK_CRITERIA, str(source_repo))

    assert attempts == 3  # ровно 3 попытки, без «мусорного» вердикта
    assert "исчерпан" in str(exc_info.value)
    assert _detector_temp_dirs() == before  # клон удалён даже при устойчивом сбое LLM
