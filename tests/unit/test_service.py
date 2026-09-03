"""Юнит-тесты AIDetectionService: оркестрация пайплайна, параллельность, очистка (FR-001, FR-006, FR-007, FR-010).

Подмена: все четыре подсистемы (cloner/extractor/aggregator/judge) — фейками;
llm_client не используется, т.к. judge подменяется целиком.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_detector.code_aggregator import LocalCodeAggregator
from ai_detector.exceptions import MetadataExtractionError
from ai_detector.git_metadata import GitMetadataExtractor
from ai_detector.llm_judge import LLMJudge
from ai_detector.models import AIAssessmentResult, CommitInfo
from ai_detector.repo_cloner import RepoCloner
from ai_detector.service import AIDetectionService

REPO_PATH = Path("/tmp/fake-clone") / "repo"
REPO_URL = "https://github.com/o/r.git"
COMMIT = CommitInfo(
    hash="cd34" * 10,
    author="student",
    date="2026-03-02T09:15:00+03:00",
    message="добавлен LRU-кеш",
)
FILE_TREE = ["lru.py", "README.md"]
FULL_CODE = "--- FILE: lru.py ---\nкод целиком\n--- END FILE ---"


def make_result(status: str = "green") -> AIAssessmentResult:
    return AIAssessmentResult(
        status=status,
        confidence=0.8,
        reasoning="причина",
        ai_indicators=[],
        human_indicators=["осмысленные коммиты"],
    )


class FakeCloner:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.cleanup_called = False

    @asynccontextmanager
    async def clone(self, repo_url: str):
        self.urls.append(repo_url)
        self.cleanup_called = False
        try:
            yield REPO_PATH
        finally:
            self.cleanup_called = True


class GatedFake:
    """Фейк, который фиксирует старт и (опционально) ждёт gate — доказательство параллельного запуска."""

    def __init__(self, gate: asyncio.Event | None, events: list[str], name: str) -> None:
        self._gate = gate
        self._events = events
        self._name = name

    async def _run(self) -> None:
        self._events.append(f"{self._name}:started")
        if self._gate is not None:
            await self._gate.wait()
        self._events.append(f"{self._name}:finished")


class FakeExtractor(GatedFake):
    async def extract(self, repo_path: Path) -> tuple[list[CommitInfo], list[str]]:
        await self._run()
        return [COMMIT], FILE_TREE


class FakeAggregator(GatedFake):
    async def aggregate(self, repo_path: Path) -> str:
        await self._run()
        return FULL_CODE


class FakeJudge:
    def __init__(self, result: AIAssessmentResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def evaluate(
        self, task_criteria: str, file_tree: list[str], commits: list[CommitInfo], full_code: str
    ) -> AIAssessmentResult:
        self.calls.append(
            {"task_criteria": task_criteria, "file_tree": file_tree, "commits": commits, "full_code": full_code}
        )
        return self.result


def build_service(
    result: AIAssessmentResult | None = None,
    gate: asyncio.Event | None = None,
    events: list[str] | None = None,
) -> tuple[AIDetectionService, FakeCloner, FakeJudge]:
    events = events if events is not None else []
    cloner = FakeCloner()
    judge = FakeJudge(result or make_result())
    service = AIDetectionService(SimpleNamespace())  # type: ignore[arg-type]
    service._cloner = cloner
    service._extractor = FakeExtractor(gate, events, "extract")
    service._aggregator = FakeAggregator(gate, events, "aggregate")
    service._judge = judge
    return service, cloner, judge


def test_init_builds_all_subsystems_without_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Конструктор чистый: создаёт все подсистемы, без сети, git и чтения окружения."""
    monkeypatch.delenv("AI_DETECTOR_LLM_MODEL", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AI_DETECTOR_GIT_TOKEN", raising=False)
    service = AIDetectionService(SimpleNamespace())  # type: ignore[arg-type]
    assert isinstance(service._cloner, RepoCloner)
    assert isinstance(service._extractor, GitMetadataExtractor)
    assert isinstance(service._aggregator, LocalCodeAggregator)
    assert isinstance(service._judge, LLMJudge)


async def test_analyze_runs_extract_and_aggregate_in_parallel() -> None:
    """FR-006: git log и чтение файлов стартуют ДО завершения друг друга (обобщённый gather)."""
    gate = asyncio.Event()
    events: list[str] = []
    service, _cloner, judge = build_service(gate=gate, events=events)

    task = asyncio.create_task(service.analyze("критерий", REPO_URL))
    while not {"extract:started", "aggregate:started"} <= set(events):
        await asyncio.sleep(0.005)
    assert not any(e.endswith(":finished") for e in events)  # оба ещё выполняются — параллельность доказана
    gate.set()

    result = await task
    assert result.status == "green"
    assert len(judge.calls) == 1


async def test_analyze_forwards_full_payload_and_returns_judge_result() -> None:
    """FR-007: judge получает task_criteria, file_tree, commits, full_code; вердикт пробрасывается наружу."""
    expected = make_result(status="yellow")
    service, cloner, judge = build_service(result=expected)

    returned = await service.analyze("Реализовать LRU-кеш", REPO_URL)

    assert returned is expected
    (call,) = judge.calls
    assert call["task_criteria"] == "Реализовать LRU-кеш"
    assert call["file_tree"] == FILE_TREE
    assert call["commits"] == [COMMIT]
    assert call["full_code"] == FULL_CODE
    assert cloner.urls == [REPO_URL]
    assert cloner.cleanup_called is True  # FR-010: временный каталог закрыт


async def test_analyze_cleans_clone_on_pipeline_failure() -> None:
    """FR-010: сбой экстрактора → исключение наружу И временный клон удалён."""

    class FailingExtractor:
        async def extract(self, repo_path: Path) -> tuple[list[CommitInfo], list[str]]:
            raise MetadataExtractionError("git log завершился с ошибкой: не репозиторий")

    service, cloner, _judge = build_service()
    service._extractor = FailingExtractor()

    with pytest.raises(MetadataExtractionError):
        await service.analyze("критерий", REPO_URL)
    assert cloner.cleanup_called is True
