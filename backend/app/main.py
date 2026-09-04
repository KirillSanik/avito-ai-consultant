from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from io import BytesIO

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from weasyprint import HTML

from .database import Base, SessionLocal, engine, get_db
from .models import Assignment, ClarificationRequest, Course, Submission
from .schemas import (
    AssignmentListOut,
    AssignmentOut,
    ClarificationCreate,
    ClarificationOut,
    CourseOut,
    CriteriaUpdate,
    ReviewUpdate,
    SubmissionOut,
)
from .tasks import deadline_reminder


def seed_demo_data() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count(Course.id))):
            return

        course = Course(title="Аналитика данных", year=2026, cohort="Осенний поток")
        assignment = Assignment(
            title="Исследование продуктовой метрики",
            deadline=datetime(2026, 9, 12, 23, 59),
            task_url="https://github.com/ai-talent-hub-avito/homework_examples",
            criteria=[
                {"title": "Корректность анализа", "max_score": 40},
                {"title": "Аргументация выводов", "max_score": 30},
                {"title": "Структура и оформление", "max_score": 20},
                {"title": "Самостоятельность", "max_score": 10},
            ],
            reviewer_guide=(
                "Проверьте воспроизводимость расчётов и связь выводов с данными. "
                "AI-оценка является только черновиком."
            ),
        )
        assignment.submissions = [
            Submission(
                student_name="Анна Смирнова",
                work_url="https://github.com/example/analytics-homework/pull/12",
                stepik_url="https://stepik.org/users/1001",
                status="in_review",
                reviewer="Демо Ревьюер",
            ),
            Submission(
                student_name="Михаил Орлов",
                work_url="https://github.com/example/analytics-homework/pull/15",
                stepik_url="https://stepik.org/users/1002",
                status="pending",
            ),
            Submission(
                student_name="Елена Волкова",
                work_url="https://github.com/example/analytics-homework/pull/17",
                stepik_url="https://stepik.org/users/1003",
                status="reviewed",
                reviewer="Иван Петров",
                score=82,
                summary="Расчёты верны, выводы стоит связать с продуктовыми решениями.",
            ),
        ]
        second_assignment = Assignment(
            title="A/B-тест: принятие решения",
            deadline=datetime(2026, 9, 19, 23, 59),
            task_url="https://github.com/ai-talent-hub-avito/homework_examples",
            criteria=[
                {"title": "Выбор статистического критерия", "max_score": 35},
                {"title": "Расчёты и воспроизводимость", "max_score": 35},
                {"title": "Продуктовый вывод", "max_score": 30},
            ],
            reviewer_guide="Проверьте предпосылки теста, расчёт эффекта и практический вывод.",
        )
        second_assignment.submissions = [
            Submission(
                student_name="Анна Смирнова",
                work_url="https://github.com/example/analytics-homework/pull/22",
                stepik_url="https://stepik.org/users/1001",
                status="pending",
            ),
            Submission(
                student_name="Михаил Орлов",
                work_url="https://github.com/example/analytics-homework/pull/24",
                stepik_url="https://stepik.org/users/1002",
                status="pending",
            ),
        ]
        course.assignments.extend([assignment, second_assignment])
        db.add(course)
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_demo_data()
    yield


app = FastAPI(title="AI Reviewer API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/courses", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db)) -> list[CourseOut]:
    courses = db.scalars(
        select(Course).options(selectinload(Course.assignments)).order_by(Course.year.desc())
    ).all()
    return [
        CourseOut(
            id=course.id,
            title=course.title,
            year=course.year,
            cohort=course.cohort,
            assignments_count=len(course.assignments),
        )
        for course in courses
    ]


@app.get("/api/courses/{course_id}/assignments", response_model=list[AssignmentListOut])
def list_assignments(course_id: int, db: Session = Depends(get_db)) -> list[AssignmentListOut]:
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.course_id == course_id)
        .options(selectinload(Assignment.submissions))
    ).all()
    return [
        AssignmentListOut(
            id=item.id,
            title=item.title,
            deadline=item.deadline,
            total=len(item.submissions),
            reviewed=sum(submission.status == "reviewed" for submission in item.submissions),
        )
        for item in assignments
    ]


def get_assignment_or_404(assignment_id: int, db: Session) -> Assignment:
    assignment = db.scalar(
        select(Assignment)
        .where(Assignment.id == assignment_id)
        .options(selectinload(Assignment.submissions))
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


@app.get("/api/assignments/{assignment_id}", response_model=AssignmentOut)
def get_assignment(assignment_id: int, db: Session = Depends(get_db)) -> AssignmentOut:
    assignment = get_assignment_or_404(assignment_id, db)
    return AssignmentOut(
        id=assignment.id,
        course_id=assignment.course_id,
        title=assignment.title,
        deadline=assignment.deadline,
        task_url=assignment.task_url,
        criteria=assignment.criteria,
        reviewer_guide=assignment.reviewer_guide,
        submissions=[SubmissionOut.model_validate(item) for item in assignment.submissions],
    )


@app.put("/api/assignments/{assignment_id}/criteria", response_model=AssignmentOut)
def update_criteria(
    assignment_id: int,
    payload: CriteriaUpdate,
    db: Session = Depends(get_db),
) -> AssignmentOut:
    assignment = get_assignment_or_404(assignment_id, db)
    assignment.criteria = [item.model_dump() for item in payload.criteria]
    assignment.reviewer_guide = payload.reviewer_guide
    db.commit()
    return get_assignment(assignment_id, db)


@app.post("/api/submissions/{submission_id}/ai-draft", response_model=SubmissionOut)
def create_ai_draft(submission_id: int, db: Session = Depends(get_db)) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    criteria = submission.assignment.criteria
    draft_scores = [
        {
            "criterion": item["title"],
            "score": max(1, round(item["max_score"] * 0.8)),
            "max_score": item["max_score"],
            "comment": "Критерий в основном выполнен; проверьте выводы вручную.",
        }
        for item in criteria
    ]
    submission.ai_draft = {
        "scores": draft_scores,
        "total": sum(item["score"] for item in draft_scores),
        "summary": "Работа структурирована, расчёты выглядят последовательно. Нужна ручная проверка источников.",
        "integrity": {
            "confidence": 0.27,
            "reason": "Недостаточно признаков для вывода об использовании генеративного AI.",
        },
    }
    submission.status = "in_review"
    submission.reviewer = submission.reviewer or "Демо Ревьюер"
    db.commit()
    db.refresh(submission)
    return submission


@app.put("/api/submissions/{submission_id}/review", response_model=SubmissionOut)
def save_review(
    submission_id: int,
    payload: ReviewUpdate,
    db: Session = Depends(get_db),
) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    submission.score = payload.score
    submission.summary = payload.summary
    submission.integrity_flag = payload.integrity_flag
    submission.status = "reviewed"
    submission.reviewer = submission.reviewer or "Демо Ревьюер"
    db.commit()
    db.refresh(submission)
    return submission


@app.get("/api/assignments/{assignment_id}/next", response_model=SubmissionOut)
def next_submission(assignment_id: int, db: Session = Depends(get_db)) -> Submission:
    submission = db.scalar(
        select(Submission)
        .where(
            Submission.assignment_id == assignment_id,
            Submission.status.in_(["pending", "in_review"]),
        )
        .order_by(Submission.status.desc(), Submission.id)
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="No submissions left")
    if submission.status == "pending":
        submission.status = "in_review"
        submission.reviewer = "Демо Ревьюер"
        db.commit()
        db.refresh(submission)
    return submission


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    submissions = db.scalars(select(Submission)).all()
    clarifications = db.scalars(
        select(ClarificationRequest).order_by(ClarificationRequest.created_at.desc())
    ).all()
    reviewed = [item for item in submissions if item.status == "reviewed"]
    return {
        "total": len(submissions),
        "reviewed": len(reviewed),
        "in_progress": sum(item.status == "in_review" for item in submissions),
        "reviewers": [
            {"name": "Демо Ревьюер", "reviewed": 0, "active": 1, "anomaly": False},
            {"name": "Иван Петров", "reviewed": 1, "active": 0, "anomaly": False},
            {"name": "Ольга Ким", "reviewed": 8, "active": 4, "anomaly": True},
        ],
        "clarifications": [
            ClarificationOut.model_validate(item).model_dump(mode="json")
            for item in clarifications
        ],
    }


@app.post(
    "/api/assignments/{assignment_id}/clarifications",
    response_model=ClarificationOut,
)
def create_clarification(
    assignment_id: int,
    payload: ClarificationCreate,
    db: Session = Depends(get_db),
) -> ClarificationRequest:
    get_assignment_or_404(assignment_id, db)
    request = ClarificationRequest(
        assignment_id=assignment_id,
        author="Демо Ревьюер",
        message=payload.message,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@app.post("/api/assignments/{assignment_id}/deadline-reminder")
def enqueue_deadline_reminder(assignment_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    assignment = get_assignment_or_404(assignment_id, db)
    task = deadline_reminder.delay(
        assignment.course.title,
        assignment.title,
        assignment.deadline.isoformat(),
    )
    return {"status": "queued", "task_id": task.id}


@app.get("/api/submissions/{submission_id}/report.pdf")
def download_report(submission_id: int, db: Session = Depends(get_db)) -> Response:
    submission = db.get(Submission, submission_id)
    if submission is None or submission.status != "reviewed":
        raise HTTPException(status_code=404, detail="Completed review not found")

    student_name = escape(submission.student_name)
    summary = escape(submission.summary or "")
    integrity = escape(submission.integrity_flag or "Нарушения не отмечены")
    html = f"""
    <html lang="ru"><meta charset="utf-8">
    <style>body {{ font-family: sans-serif; margin: 48px; }} h1 {{ color: #222; }}</style>
    <body>
      <h1>Отчёт по проверке</h1>
      <p><b>Студент:</b> {student_name}</p>
      <p><b>Итог:</b> {submission.score}/100</p>
      <h2>Комментарий</h2><p>{summary}</p>
      <h2>Самостоятельность</h2><p>{integrity}</p>
    </body></html>
    """
    output = BytesIO()
    HTML(string=html).write_pdf(output)
    return Response(
        output.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="review-{submission_id}.pdf"'},
    )
