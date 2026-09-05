"""Opt-in full HTTP integration test with real OpenRouter calls and data files.

Run with ``RUN_LIVE_OPENROUTER=1 uv run pytest -s
tests/integration/test_live_http_endpoints.py``. This test deliberately uses
no HTTP interception, fake client, or mocked pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from common.settings import get_settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_OPENROUTER") != "1",
    reason="set RUN_LIVE_OPENROUTER=1 to run live OpenRouter HTTP integration",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = PROJECT_ROOT / "data" / "Product_Fraud_hw2.pdf"
SOLUTION_FILE = PROJECT_ROOT / "data" / "Product_Fraud_hw2_solution_weak.docx"


def test_live_all_persistent_http_routes(tmp_path: Path) -> None:
    """Exercise health, writes, reads, status, evaluation, and PDF download."""
    if not get_settings().openrouter_api_key:
        pytest.fail("OPENROUTER_API_KEY must be configured for this live test")
    assert TASK_FILE.is_file()
    assert SOLUTION_FILE.is_file()
    previous_database = os.environ.get("DATABASE_URL")
    previous_storage = os.environ.get("STORAGE_DIR")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'live.db'}"
    os.environ["STORAGE_DIR"] = str(tmp_path / "storage")
    get_settings.cache_clear()
    try:
        with TestClient(app_module.app) as client:
            assert client.get("/health").status_code == 200
            users = (
                ("methodist-live", "methodist"),
                ("student-live", "student"),
                ("reviewer-live", "reviewer"),
            )
            for user_id, role in users:
                response = client.post(
                    "/api/v1/users/register",
                    data={"user_id": user_id, "role": role, "name": user_id},
                )
                assert response.status_code == 201, response.text
            task_response = client.post(
                "/api/v1/tasks",
                data={"course_id": "fraud-live", "title": "Fraud homework"},
                files={"file": (TASK_FILE.name, TASK_FILE.read_bytes(), "application/pdf")},
            )
            assert task_response.status_code == 201, task_response.text
            task_id = task_response.json()["id"]
            assert client.get(f"/api/v1/tasks/{task_id}").status_code == 200
            submission_response = client.post(
                "/api/v1/submissions",
                data={"task_id": task_id, "student_id": "student-live"},
                files={
                    "file": (
                        SOLUTION_FILE.name,
                        SOLUTION_FILE.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert submission_response.status_code == 201, submission_response.text
            submission_id = submission_response.json()["submission_id"]
            assert client.get(f"/api/v1/submissions/{submission_id}").status_code == 200
            evaluation_response = client.get("/api/v1/evaluations", params={"submission_id": submission_id})
            assert evaluation_response.status_code == 200, evaluation_response.text
            assert evaluation_response.json()["review_json"]["evaluation"]["criterion_results"]
            pdf_response = client.get(f"/api/v1/evaluations/{submission_id}/pdf")
            assert pdf_response.status_code == 200
            assert pdf_response.content.startswith(b"%PDF")
    finally:
        if previous_database is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database
        if previous_storage is None:
            os.environ.pop("STORAGE_DIR", None)
        else:
            os.environ["STORAGE_DIR"] = previous_storage
        get_settings.cache_clear()
