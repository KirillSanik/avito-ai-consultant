import asyncio
from types import MethodType, SimpleNamespace

from app.services.contracts import Criterion, SubmissionData, TaskRubric
from app.services.llm import LLMService


def test_grade_criteria_accepts_criteria_id_and_score_contract() -> None:
    service = object.__new__(LLMService)
    service.settings = SimpleNamespace(max_input_chars=10_000)

    async def fake_json(self, system: str, user: str) -> dict:
        return {
            "criteria": [
                {"criteria_id": "0", "score": 2.5, "reasoning": "Первый критерий выполнен.", "evidence": ["result"]},
                {"criteria_id": "1", "score": 1.25, "reasoning": "Второй критерий выполнен частично.", "evidence": []},
            ]
        }

    service._json = MethodType(fake_json, service)
    rubric = TaskRubric(
        task_id="task",
        title="Task",
        criteria=[
            Criterion(name="Первый", max_points=3.5),
            Criterion(name="Второй", max_points=2.0),
        ],
    )
    submission = SubmissionData(submission_id="submission", task_id="task", file_type="txt", raw_text="Работа")

    results = asyncio.run(service.grade_criteria(rubric, submission))

    assert [item.assigned_score for item in results] == [2.5, 1.25]
    assert [item.reasoning for item in results] == ["Первый критерий выполнен.", "Второй критерий выполнен частично."]
