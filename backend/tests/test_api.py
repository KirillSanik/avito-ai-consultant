from fastapi.testclient import TestClient

from app.main import app


def test_main_reviewer_flow() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}

        courses = client.get("/api/courses")
        assert courses.status_code == 200
        course_id = courses.json()[0]["id"]

        assignments = client.get(f"/api/courses/{course_id}/assignments")
        assignment_id = assignments.json()[0]["id"]

        assignment = client.get(f"/api/assignments/{assignment_id}")
        assert assignment.status_code == 200
        submission_id = assignment.json()["submissions"][0]["id"]

        draft = client.post(f"/api/submissions/{submission_id}/ai-draft")
        assert draft.status_code == 200
        assert draft.json()["ai_draft"]["total"] > 0

        review = client.put(
            f"/api/submissions/{submission_id}/review",
            json={
                "score": 84,
                "summary": "Хорошая работа, стоит усилить аргументацию.",
                "integrity_flag": None,
            },
        )
        assert review.status_code == 200
        assert review.json()["status"] == "reviewed"

        report = client.get(f"/api/submissions/{submission_id}/report.pdf")
        assert report.status_code == 200
        assert report.headers["content-type"] == "application/pdf"


def test_methodist_dashboard() -> None:
    with TestClient(app) as client:
        course_id = client.get("/api/courses").json()[0]["id"]
        assignment_id = client.get(f"/api/courses/{course_id}/assignments").json()[0]["id"]
        clarification = client.post(
            f"/api/assignments/{assignment_id}/clarifications",
            json={"message": "Нужно ли учитывать альтернативный способ расчёта?"},
        )
        assert clarification.status_code == 200

        response = client.get("/api/dashboard")
        assert response.status_code == 200
        assert response.json()["total"] >= 3
        assert len(response.json()["reviewers"]) >= 1
        assert len(response.json()["clarifications"]) >= 1
