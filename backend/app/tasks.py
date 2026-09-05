import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from celery import Celery
from .database import SessionLocal
from .models import Evaluation, Submission
from .services.contracts import TaskRubric
from .services.pipeline import EvaluationPipeline
from .services.reporting import generate_review_pdf


celery_app = Celery(
    "ai_reviewer",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",
)


@celery_app.task(name="notifications.deadline_reminder")
def deadline_reminder(course: str, assignment: str, deadline: str) -> dict[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {
            "status": "skipped",
            "reason": "Telegram credentials are not configured",
        }

    message = (
        f"Напоминание о дедлайне\n\n"
        f"Курс: {course}\n"
        f"Задание: {assignment}\n"
        f"Дедлайн: {deadline}"
    )

    async def send() -> None:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=message)

    asyncio.run(send())
    return {
        "status": "sent",
        "course": course,
        "assignment": assignment,
        "deadline": deadline,
    }


@celery_app.task(name="evaluations.evaluate_submission")
def evaluate_submission_task(submission_id: int) -> dict[str, object]:
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        if submission is None:
            return {"status": "missing", "submission_id": submission_id}
        assignment = submission.assignment
        if assignment is None:
            submission.evaluation_status = "failed"
            db.commit()
            return {"status": "failed", "submission_id": submission_id, "reason": "assignment missing"}
        evaluation = Evaluation(
            submission_id=submission.id,
            rubric_version=assignment.criteria_version,
            status="processing",
        )
        db.add(evaluation)
        submission.evaluation_status = "processing"
        db.commit()
        db.refresh(evaluation)
        try:
            rubric = TaskRubric.model_validate(assignment.rubric_json or {
                "task_id": str(assignment.id),
                "title": assignment.title,
                "description": assignment.reviewer_guide,
                "full_instructions": assignment.task_text or assignment.reviewer_guide,
                "criteria": [
                    {
                        "name": item.get("title", "Criterion"),
                        "description": item.get("description", ""),
                        "max_points": item.get("max_score", 0),
                    }
                    for item in assignment.criteria
                ],
                "total_points": sum(item.get("max_score", 0) for item in assignment.criteria),
            })
            source_type = submission.source_type or "url"
            source = submission.source_file_path if source_type == "file" else submission.work_url
            if not source:
                raise ValueError("submission source is missing")
            result = asyncio.run(EvaluationPipeline().run(str(submission.id), source_type, source, rubric))
            report_path = Path(os.getenv("STORAGE_DIR", "./storage")) / "reports" / f"submission-{submission.id}-evaluation-{evaluation.id}.pdf"
            generate_review_pdf(result.evaluation, rubric, result.ai_assessment, report_path)
            evaluation.review_json = result.evaluation.model_dump(mode="json")
            evaluation.ai_assessment_json = result.ai_assessment.model_dump(mode="json")
            evaluation.total_score = result.evaluation.total_score
            evaluation.max_total_score = result.evaluation.max_total_score
            evaluation.pdf_report_path = str(report_path)
            evaluation.status = "completed"
            evaluation.completed_at = datetime.now(timezone.utc)
            submission.latest_evaluation_id = evaluation.id
            submission.evaluation_status = "completed"
            submission.ai_draft = {
                "scores": [
                    {
                        "criterion": item.criterion_name,
                        "score": item.assigned_score,
                        "max_score": item.max_points,
                        "comment": item.reasoning,
                        "evidence": item.evidence,
                    }
                    for item in result.evaluation.criterion_results
                ],
                "total": result.evaluation.total_score,
                "summary": result.evaluation.summary_feedback,
                "integrity": result.ai_assessment.model_dump(mode="json"),
            }
            db.commit()
            return {"status": "completed", "submission_id": submission_id, "evaluation_id": evaluation.id}
        except Exception as exc:
            evaluation.status = "failed"
            evaluation.error_message = str(exc)[:4000]
            evaluation.completed_at = datetime.now(timezone.utc)
            submission.evaluation_status = "failed"
            db.commit()
            return {"status": "failed", "submission_id": submission_id, "evaluation_id": evaluation.id}
