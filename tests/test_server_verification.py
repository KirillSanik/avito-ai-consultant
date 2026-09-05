"""End-to-end API verification with deterministic LLM-free review doubles.

Run with ``uv run pytest -s tests/test_server_verification.py``.  The test
boots the actual FastAPI lifespan, SQLite schema and filesystem report path;
only external LLM calls are replaced so it is runnable in CI.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from common.models import (
    AIAssessmentResult,
    Criterion,
    CriterionResult,
    EvaluationReport,
    ReviewResponse,
    TaskRubric,
)


def test_server_database_and_storage_verification(monkeypatch, tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'review.db'}")
    monkeypatch.setenv("STORAGE_DIR", str(storage))
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    app_module.get_settings.cache_clear()

    async def fake_parse(_text: str, task_id: str, **_kwargs: object) -> TaskRubric:
        return TaskRubric(
            task_id=task_id,
            title="Smoke task",
            description="Verify the service",
            full_instructions="Write a small Python program.",
            criteria=[Criterion(name="Correctness", description="Program exists", max_points=10)],
            total_points=10,
        )

    class FakePipeline:
        def _rubric_client(self) -> object:
            return object()

        async def run_preparsed(self, repo_url: str, criteria: object) -> ReviewResponse:
            return self._result(repo_url, criteria)  # type: ignore[arg-type]

        async def run_from_path(self, repo_url: str, criteria: object, _path: Path) -> ReviewResponse:
            return self._result(repo_url, criteria)  # type: ignore[arg-type]

        @staticmethod
        def _result(repo_url: str, criteria: object) -> ReviewResponse:
            evaluation = EvaluationReport(
                task_id=criteria.task_id,  # type: ignore[union-attr]
                submission_id="smoke-submission",
                total_score=10,
                max_total_score=10,
                criterion_results=[
                    CriterionResult(
                        criterion_id="criterion-1", criterion_name="Correctness", assigned_score=10,
                        max_points=10, reasoning="Работа содержит проверяемую реализацию.", evidence=["solution.py"],
                    )
                ],
                summary_feedback="Итог: 10 из 10 баллов.",
            )
            return ReviewResponse(
                repo_url=repo_url,
                task_id=criteria.task_id,  # type: ignore[union-attr]
                ai_assessment=AIAssessmentResult(
                    status="green",
                    confidence=0.9,
                    reasoning="Есть признаки самостоятельной работы и проверяемая реализация.",
                    ai_indicators=[], human_indicators=["Локальный файл решения"],
                ),
                evaluation=evaluation,
            )

    monkeypatch.setattr(app_module, "parse_task_rubric", fake_parse)
    monkeypatch.setattr(app_module, "extract_task_text", lambda _path: "Write a small Python program.")
    with TestClient(app_module.app) as client:
        # Lifespan created a real pipeline; use the deterministic external-service double.
        client.app.state.pipeline = FakePipeline()
        for user_id, role in (("methodist-1", "methodist"), ("student-1", "student"), ("reviewer-1", "reviewer")):
            response = client.post("/api/v1/users/register", data={"user_id": user_id, "role": role, "name": user_id})
            assert response.status_code == 201, response.text

        task_response = client.post(
            "/api/v1/tasks",
            data={"course_id": "course-1", "title": "Smoke task"},
            files={
                "file": (
                    "condition.docx",
                    b"placeholder",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert task_response.status_code == 201, task_response.text
        task = task_response.json()
        assert task["rubric_json"]["criteria"][0]["max_points"] == 10
        assert list((storage / "tasks").glob("*.docx"))

        submission_response = client.post(
            "/api/v1/submissions",
            data={"task_id": task["id"], "student_id": "student-1"},
            files={"file": ("solution.py", b"print('ok')\n", "text/x-python")},
        )
        assert submission_response.status_code == 201, submission_response.text
        submission = submission_response.json()
        assert submission["review_json"]["evaluation"]["total_score"] == 10
        assert list((storage / "submissions").glob("*.py"))
        assert list((storage / "reports").glob("*.pdf"))

        evaluation_response = client.get("/api/v1/evaluations", params={"submission_id": submission["submission_id"]})
        assert evaluation_response.status_code == 200, evaluation_response.text
        assert evaluation_response.json()["review_json"]["ai_assessment"]["status"] == "green"
        pdf_response = client.get(submission["pdf_url"])
        assert pdf_response.status_code == 200
        assert pdf_response.headers["content-type"].startswith("application/pdf")
        assert pdf_response.content.startswith(b"%PDF")
    print("VERIFIED: FastAPI, SQLite tables, persistent uploads, evaluation and PDF are fully functional.")
