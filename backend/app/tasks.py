import asyncio
import logging
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from celery import Celery
import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from .database import SessionLocal
from .models import Assignment, EnrollmentApplication, Evaluation, Submission, User
from .services.contracts import TaskRubric
from .services.parsers import extract_url_text
from .services.pipeline import EvaluationPipeline
from .services.reporting import generate_review_pdf

logger = logging.getLogger(__name__)


redis_url = os.getenv("REDIS_URL", "")
celery_app = Celery(
    "ai_reviewer",
    broker=redis_url or "memory://",
    backend=redis_url or "cache+memory://",
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",
    broker_connection_timeout=2,
    broker_connection_retry=False,
)
celery_app.conf.beat_schedule = {
    "dispatch-deadline-reminders-hourly": {
        "task": "notifications.dispatch_due_deadline_reminders",
        "schedule": 3600.0,
    },
}
if not redis_url:
    # Локальный запуск без Redis: задачи выполняются синхронно в процессе API.
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False


@celery_app.task(name="notifications.deadline_reminder")
def deadline_reminder(course: str, assignment: str, deadline: str, chat_id: str | None = None, dry_run: bool = False) -> dict[str, str]:
    """Send one JSON-safe reminder through tg-notify; failure never raises into Celery."""
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    notify_url = os.getenv("TG_NOTIFY_URL", "").strip()
    api_key = os.getenv("TG_NOTIFY_API_KEY", "").strip()
    if not notify_url or not api_key or not chat_id:
        logger.warning("deadline_reminder.skipped course=%s assignment=%s configured=%s chat_id=%s", course, assignment, bool(notify_url and api_key), bool(chat_id))
        return {
            "status": "skipped",
            "reason": "tg-notify URL, API key, or chat_id is not configured",
        }

    message = (
        f"Напоминание о дедлайне\n\n"
        f"Курс: {course}\n"
        f"Задание: {assignment}\n"
        f"Дедлайн: {deadline}"
    )

    payload = {"chat_id": str(chat_id), "text": message}
    if dry_run:
        logger.info("deadline_reminder.dry_run url=%s payload=%s", notify_url, payload)
        return {"status": "dry_run", "course": course, "assignment": assignment, "deadline": deadline}
    try:
        response = httpx.post(
            notify_url,
            json=payload,
            headers={"X-API-Key": api_key},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        response = getattr(exc, "response", None)
        logger.error("deadline_reminder.failed chat_id=%s error=%s body=%s", chat_id, exc, (response.text if response is not None else "")[:2000])
        return {"status": "failed", "course": course, "assignment": assignment, "deadline": deadline}
    logger.info("deadline_reminder.sent chat_id=%s assignment=%s", chat_id, assignment)
    return {
        "status": "sent",
        "course": course,
        "assignment": assignment,
        "deadline": deadline,
    }


def _student_chat_id(student: User) -> str | None:
    """Resolve a Telegram numeric chat id without treating a public @username as one."""
    mapping_raw = os.getenv("TG_NOTIFY_CHAT_IDS", "{}") or "{}"
    try:
        mapping = json.loads(mapping_raw)
    except json.JSONDecodeError:
        logger.error("TG_NOTIFY_CHAT_IDS must be a JSON object")
        mapping = {}
    for key in (str(student.id), student.login, student.telegram.removeprefix("@")):
        value = mapping.get(key) if isinstance(mapping, dict) else None
        if value is not None:
            return str(value)
    value = student.telegram.strip()
    return value if value.lstrip("-").isdigit() else None


@celery_app.task(name="notifications.dispatch_due_deadline_reminders")
def dispatch_due_deadline_reminders(dry_run: bool = False, now_iso: str | None = None) -> dict[str, int]:
    """Find enrolled students whose assignments are due in the next 24 hours."""
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)  # assignment.deadline is stored as a naive local datetime
    until = now + timedelta(hours=24)
    db = SessionLocal()
    dispatched = skipped = failed = 0
    try:
        rows = db.execute(
            select(Assignment, User)
            .join(EnrollmentApplication, EnrollmentApplication.course_id == Assignment.course_id)
            .join(User, User.id == EnrollmentApplication.user_id)
            .where(
                EnrollmentApplication.status == "enrolled",
                Assignment.deadline >= now,
                Assignment.deadline <= until,
            )
        ).all()
        logger.info("deadline_reminder.dispatch_scan now=%s until=%s candidates=%s dry_run=%s", now.isoformat(), until.isoformat(), len(rows), dry_run)
        for assignment, student in rows:
            chat_id = _student_chat_id(student)
            if not chat_id:
                skipped += 1
                logger.warning("deadline_reminder.skipped_missing_chat_id assignment_id=%s student_id=%s telegram=%r", assignment.id, student.id, student.telegram)
                continue
            result = deadline_reminder.run(assignment.course.title, assignment.title, assignment.deadline.isoformat(), chat_id, dry_run)
            if result["status"] in {"sent", "dry_run"}:
                dispatched += 1
            elif result["status"] == "failed":
                failed += 1
            else:
                skipped += 1
        return {"status": "dry_run" if dry_run else "completed", "dispatched": dispatched, "skipped": skipped, "failed": failed}
    finally:
        db.close()


@celery_app.task(name="evaluations.evaluate_submission")
def evaluate_submission_task(submission_id: int) -> dict[str, object]:
    logger.info("evaluation.task.started submission_id=%s", submission_id)
    db = SessionLocal()
    evaluation = None
    submission = None
    try:
        submission = db.scalar(
            select(Submission)
            .where(Submission.id == submission_id)
            .options(selectinload(Submission.assignment))
            .with_for_update()
        )
        if submission is None:
            db.rollback()
            return {"status": "missing", "submission_id": submission_id}
        existing_evaluation = db.scalar(
            select(Evaluation)
            .where(Evaluation.submission_id == submission.id)
            .order_by(Evaluation.created_at.desc(), Evaluation.id.desc())
        )
        if existing_evaluation is not None:
            logger.info(
                "evaluation.task.skipped_existing submission_id=%s evaluation_id=%s status=%s",
                submission.id,
                existing_evaluation.id,
                existing_evaluation.status,
            )
            db.rollback()
            return {
                "status": existing_evaluation.status,
                "submission_id": submission_id,
                "evaluation_id": existing_evaluation.id,
            }
        if submission.evaluation_status != "queued":
            logger.info(
                "evaluation.task.skipped_not_queued submission_id=%s status=%s",
                submission.id,
                submission.evaluation_status,
            )
            db.rollback()
            return {"status": submission.evaluation_status, "submission_id": submission_id}
        claim = db.execute(
            update(Submission)
            .where(
                Submission.id == submission.id,
                Submission.evaluation_status == "queued",
            )
            .values(evaluation_status="processing")
        )
        if claim.rowcount != 1:
            db.rollback()
            return {"status": "skipped", "submission_id": submission_id}
        db.refresh(submission)
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
        db.commit()
        db.refresh(evaluation)
        logger.info("evaluation.status.processing submission_id=%s evaluation_id=%s", submission.id, evaluation.id)
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
            logger.info(
                "evaluation.prompt_context submission_id=%s assignment_id=%s task_chars=%s submission_chars=%s criteria=%s",
                submission.id,
                assignment.id,
                len(rubric.full_instructions),
                len(submission.source_text or ""),
                [criterion.model_dump(mode="json") for criterion in rubric.criteria],
            )
            source_type = submission.source_type or "url"
            source = submission.source_file_path if source_type == "file" else submission.work_url
            if not source:
                raise ValueError("submission source is missing")
            if source_type == "url" and not submission.source_text:
                submission.source_text = extract_url_text(source)
                db.commit()
                logger.info(
                    "evaluation.submission_text_persisted submission_id=%s chars=%s",
                    submission.id,
                    len(submission.source_text),
                )
            result = asyncio.run(
                EvaluationPipeline().run(
                    str(submission.id),
                    source_type,
                    source,
                    rubric,
                    submission.source_text,
                )
            )
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
            logger.info("evaluation.status.completed submission_id=%s evaluation_id=%s score=%s/%s", submission.id, evaluation.id, evaluation.total_score, evaluation.max_total_score)
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
            db.rollback()
            evaluation.status = "failed"
            evaluation.error_message = str(exc)[:4000]
            evaluation.completed_at = datetime.now(timezone.utc)
            submission.evaluation_status = "failed"
            logger.exception("evaluation.status.failed submission_id=%s evaluation_id=%s", submission.id, evaluation.id)
            db.commit()
            return {"status": "failed", "submission_id": submission_id, "evaluation_id": evaluation.id}
    except Exception as exc:
        db.rollback()
        logger.exception("evaluation.task.unhandled submission_id=%s", submission_id)
        if submission is not None:
            submission.evaluation_status = "failed"
            if evaluation is None:
                evaluation = Evaluation(submission_id=submission.id, status="failed")
                db.add(evaluation)
            evaluation.status = "failed"
            evaluation.error_message = str(exc)[:4000]
            evaluation.completed_at = datetime.now(timezone.utc)
            try:
                db.commit()
            except Exception:
                db.rollback()
        return {"status": "failed", "submission_id": submission_id, "reason": str(exc)[:4000]}
    finally:
        db.close()
