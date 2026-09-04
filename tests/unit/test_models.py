"""Тесты pydantic-моделей: форма схемы и правила валидации (data-model.md §1, §4; FR-008, FR-009)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_detector.utils.models import AIAssessmentResult, CommitInfo

VALID_COMMIT: dict[str, str] = {
    "hash": "ab12" * 10,
    "author": "student",
    "date": "2026-03-01T14:22:05+03:00",
    "message": "initial commit",
}


def _valid_result(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "green",
        "confidence": 0.8,
        "reasoning": "обоснование на русском",
        "ai_indicators": [],
        "human_indicators": ["осмысленные коммиты"],
    }
    base.update(overrides)
    return base


def test_assessment_result_has_exactly_five_fields() -> None:
    """FR-009: в схеме ровно 5 полей; task_compliance_score не существует."""
    assert set(AIAssessmentResult.model_fields) == {
        "status",
        "confidence",
        "reasoning",
        "ai_indicators",
        "human_indicators",
    }
    assert "task_compliance_score" not in AIAssessmentResult.model_fields


def test_assessment_result_validates_status_enum() -> None:
    for status in ("green", "yellow", "red"):
        result = AIAssessmentResult(**_valid_result(status=status))
        assert result.status == status
    with pytest.raises(ValidationError):
        AIAssessmentResult(**_valid_result(status="blue"))


def test_assessment_result_validates_confidence_range() -> None:
    with pytest.raises(ValidationError):
        AIAssessmentResult(**_valid_result(confidence=1.01))
    with pytest.raises(ValidationError):
        AIAssessmentResult(**_valid_result(confidence=-0.01))


def test_assessment_result_requires_nonempty_reasoning() -> None:
    with pytest.raises(ValidationError):
        AIAssessmentResult(**_valid_result(reasoning=""))


def test_assessment_result_ignores_extra_task_compliance_score() -> None:
    """Если LLM всё-таки пришлёт task_compliance_score — схема отбрасывает его (extra='ignore')."""
    payload = _valid_result(status="red")
    payload["task_compliance_score"] = 0.99
    result = AIAssessmentResult.model_validate(payload)
    assert "task_compliance_score" not in result.model_dump()


def test_commit_info_accepts_valid_record() -> None:
    commit = CommitInfo(**VALID_COMMIT)
    assert commit.hash == "ab12" * 10
    assert commit.author == "student"


def test_commit_info_rejects_short_hash() -> None:
    with pytest.raises(ValidationError):
        CommitInfo(**{**VALID_COMMIT, "hash": "abc123"})


def test_commit_info_rejects_date_without_timezone() -> None:
    with pytest.raises(ValidationError):
        CommitInfo(**{**VALID_COMMIT, "date": "2026-03-01T14:22:05"})


def test_commit_info_rejects_multiline_message() -> None:
    with pytest.raises(ValidationError):
        CommitInfo(**{**VALID_COMMIT, "message": "первая строка\nвторая строка"})


def test_commit_info_rejects_empty_author() -> None:
    with pytest.raises(ValidationError):
        CommitInfo(**{**VALID_COMMIT, "author": ""})
