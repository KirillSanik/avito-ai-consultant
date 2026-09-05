"""Opt-in live OpenRouter grading test over the checked-in Fraud task fixtures.

Run explicitly with ``RUN_LIVE_OPENROUTER=1 uv run pytest -s
tests/integration/test_live_openrouter_data.py``. No HTTP, client, or LLM
mocks are used; this test sends real structured-output requests to OpenRouter.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from common.clients import get_openrouter_client
from common.settings import Settings
from homework_reviewer.evaluator.grading_engine import GradingEngine
from homework_reviewer.parsers.submission_parser import SubmissionParser
from homework_reviewer.parsers.task_parser import TaskParser
from homework_reviewer.repository.task_repository import TaskRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_OPENROUTER") != "1",
    reason="set RUN_LIVE_OPENROUTER=1 to run paid/rate-limited live OpenRouter integration",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = PROJECT_ROOT / "data" / "Product_Fraud_hw2.pdf"
SOLUTION_FILE = PROJECT_ROOT / "data" / "Product_Fraud_hw2_solution_weak.docx"
PRIMARY_MODEL = "google/gemma-4-31b-it:free"


def test_live_task_ingestion_and_solution_evaluation(tmp_path: Path) -> None:
    """Parse the real PDF then grade its corresponding real DOCX via OpenRouter."""
    if not Settings().openrouter_api_key:
        pytest.fail("OPENROUTER_API_KEY must be configured for this live test")
    assert TASK_FILE.is_file(), TASK_FILE
    assert SOLUTION_FILE.is_file(), SOLUTION_FILE
    settings = Settings(
        llm_provider="openrouter",
        model_name=PRIMARY_MODEL,
        ai_detector_llm_provider="openrouter",
        ai_detector_llm_model=PRIMARY_MODEL,
        llm_max_tokens=4096,
    )
    client = get_openrouter_client(settings)
    rubric = asyncio.run(TaskParser(settings, client).parse_task(TASK_FILE, "live-fraud-hw2"))
    assert rubric.criteria, "OpenRouter task parsing returned no criteria"
    # Exercise task persistence as part of the real task-creation flow without
    # altering the developer's normal storage directory.
    saved_task = TaskRepository(tmp_path / "tasks").save(rubric)
    assert Path(saved_task).is_file()
    submission = SubmissionParser(settings, rubric.task_id).parse_submission(str(SOLUTION_FILE), rubric.task_id)
    report = asyncio.run(GradingEngine(client, settings).evaluate_submission(rubric, submission))
    assert report.task_id == rubric.task_id
    assert report.criterion_results
    assert 0 <= report.total_score <= report.max_total_score
