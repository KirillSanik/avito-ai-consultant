from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .allocation import (
    assign_new_submission,
    backfill_reviewer_user_ids,
    rebalance_assignment_submissions,
    recount_reviewer_stats,
)
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .models import (
    Assignment,
    AssignmentReviewer,
    AuthToken,
    ClarificationRequest,
    Course,
    CourseReviewer,
    EnrollmentApplication,
    Evaluation,
    Submission,
    User,
)
from .schemas import (
    AssignmentCreate,
    AssignmentListOut,
    AssignmentOut,
    AssignmentReviewerCreate,
    AssignmentReviewerOut,
    AssignmentReviewersBulkCreate,
    AuthResponse,
    ClarificationCreate,
    ClarificationOut,
    ClarificationUpdate,
    CourseCreate,
    CourseOut,
    CourseUpdate,
    CourseReviewerCreate,
    CourseReviewerOut,
    CriteriaUpdate,
    EnrollmentApplicationOut,
    EnrollmentDecision,
    LoginRequest,
    ReviewUpdate,
    StudentAssignmentOut,
    StudentCourseDetailOut,
    StudentCourseOut,
    StudentCreate,
    StudentSubmissionCreate,
    StudentSubmissionOut,
    SubmissionOut,
    UserCreate,
    UserOut,
    XlsxImportResult,
)
from .services.llm import LLMService
from .services.parsers import SUPPORTED_TASK_EXTENSIONS, extract_task_text, fallback_rubric
from .services.settings import PipelineSettings
from .tasks import deadline_reminder, evaluate_submission_task
from .xlsx_io import (
    XLSX_MEDIA_TYPE,
    export_assignment_workbook,
    export_course_workbook,
    parse_logins,
)

logger = logging.getLogger(__name__)


PASSWORD_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def seed_demo_data() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(func.count(User.id))):
            db.add_all(
                [
                    User(
                        login="reviewer",
                        password_hash=hash_password("reviewer"),
                        first_name="Демо",
                        last_name="Ревьюер",
                        telegram="demo_reviewer",
                        role="reviewer",
                    ),
                    User(
                        login="methodist",
                        password_hash=hash_password("methodist"),
                        first_name="Демо",
                        last_name="Методист",
                        telegram="demo_methodist",
                        role="methodist",
                    ),
                ]
            )

        if db.scalar(select(func.count(Course.id))):
            assign_demo_reviewer_if_needed(db)
            db.commit()
            return

        course = Course(
            title="Аналитика данных",
            year=2026,
            cohort="Осенний поток",
            stream=7,
            active=True,
            cover_color="#2563EB",
            students_count=28,
            capacity=30,
            description=(
                "Практический курс по продуктовой аналитике: метрики, "
                "A/B-тесты и выводы на основе данных."
            ),
        )
        assignment = Assignment(
            title="Исследование продуктовой метрики",
            number=1,
            deadline=datetime(2026, 9, 12, 23, 59),
            task_url="https://github.com/ai-talent-hub-avito/homework_examples",
            criteria_url="https://example.com/criteria/product-metrics",
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
        assignment.reviewers = [
            AssignmentReviewer(
                name="Демо Ревьюер",
                telegram="demo_reviewer",
                checked=0,
                total=2,
            ),
            AssignmentReviewer(
                name="Иван Петров",
                telegram="ivan_reviewer",
                checked=1,
                total=1,
            ),
            AssignmentReviewer(
                name="Ольга Ким",
                telegram="olga_reviewer",
                checked=8,
                total=12,
                anomaly=True,
            ),
        ]
        second_assignment = Assignment(
            title="A/B-тест: принятие решения",
            number=2,
            deadline=datetime(2026, 9, 19, 23, 59),
            task_url="https://github.com/ai-talent-hub-avito/homework_examples",
            criteria_url="https://example.com/criteria/ab-test",
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

        completed_course = Course(
            title="Основы продуктовой аналитики",
            year=2025,
            cohort="Весенний поток",
            stream=6,
            active=False,
            cover_color="#7C3AED",
            students_count=24,
            capacity=30,
            description="Базовый курс по продуктовой аналитике и работе с метриками.",
        )
        completed_assignment = Assignment(
            title="Итоговый продуктовый кейс",
            number=1,
            deadline=datetime(2025, 6, 20, 23, 59),
            task_url="https://github.com/ai-talent-hub-avito/homework_examples",
            criteria_url="https://example.com/criteria/final-case",
            criteria=[
                {"title": "Аналитическая часть", "max_score": 50},
                {"title": "Продуктовые рекомендации", "max_score": 50},
            ],
            reviewer_guide="Проверьте обоснованность выводов и практичность рекомендаций.",
        )
        completed_assignment.submissions = [
            Submission(
                student_name="Сергей Лебедев",
                work_url="https://github.com/example/product-case/pull/8",
                stepik_url="https://stepik.org/users/1004",
                status="reviewed",
                reviewer="Демо Ревьюер",
                score=91,
                summary="Сильная аналитика и применимые рекомендации.",
            )
        ]
        completed_course.assignments.append(completed_assignment)
        db.add_all([course, completed_course])
        db.flush()
        reviewer_user = db.scalar(select(User).where(User.login == "reviewer"))
        if reviewer_user is not None:
            db.add(CourseReviewer(course_id=course.id, user_id=reviewer_user.id))
            for seeded_reviewer in assignment.reviewers:
                if seeded_reviewer.telegram == reviewer_user.telegram:
                    seeded_reviewer.user_id = reviewer_user.id
        db.commit()


def assign_demo_reviewer_if_needed(db: Session) -> None:
    reviewer = db.scalar(select(User).where(User.login == "reviewer"))
    active_course = db.scalar(select(Course).where(Course.active.is_(True)).order_by(Course.id))
    if reviewer is None or active_course is None:
        return
    if not active_course.description:
        active_course.description = (
            "Практический курс по продуктовой аналитике: метрики, "
            "A/B-тесты и выводы на основе данных."
        )
    if active_course.capacity < 1:
        active_course.capacity = 30
    course_link = db.scalar(
        select(CourseReviewer.id).where(
            CourseReviewer.course_id == active_course.id,
            CourseReviewer.user_id == reviewer.id,
        )
    )
    if course_link is None:
        db.add(CourseReviewer(course_id=active_course.id, user_id=reviewer.id))
    legacy_links = db.scalars(
        select(AssignmentReviewer).where(
            AssignmentReviewer.user_id.is_(None),
            AssignmentReviewer.telegram == reviewer.telegram,
        )
    ).all()
    for link in legacy_links:
        link.user_id = reviewer.id


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    ensure_schema()
    if os.getenv("SEED_DEMO_DATA", "false").lower() in {"1", "true", "yes"}:
        seed_demo_data()
    with SessionLocal() as db:
        backfill_reviewer_user_ids(db)
    yield


app = FastAPI(title="AI Reviewer API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def create_auth_response(user: User, db: Session) -> AuthResponse:
    token = AuthToken(token=secrets.token_urlsafe(32), user_id=user.id)
    db.add(token)
    db.commit()
    return AuthResponse(token=token.token, user=UserOut.model_validate(user))


def serialize_course(course: Course) -> CourseOut:
    return CourseOut(
        id=course.id,
        title=course.title,
        year=course.year,
        cohort=course.cohort,
        stream=course.stream,
        active=course.active,
        cover_color=course.cover_color,
        students_count=course.students_count,
        assignments_count=len(course.assignments),
        description=course.description,
        capacity=course.capacity,
        enrolled_count=sum(
            item.status == "enrolled" for item in course.enrollment_applications
        ),
    )


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    token_value = authorization.removeprefix("Bearer ").strip()
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token == token_value)
        .options(selectinload(AuthToken.user))
    )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    return token.user


def require_methodist(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "methodist":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a methodist can perform this action",
        )
    return current_user


def require_student(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a student can perform this action",
        )
    return current_user


def serialize_course_reviewer(link: CourseReviewer) -> CourseReviewerOut:
    return CourseReviewerOut(
        id=link.id,
        user_id=link.user_id,
        login=link.user.login,
        first_name=link.user.first_name,
        last_name=link.user.last_name,
        telegram=link.user.telegram,
    )


def get_course_or_404(course_id: int, db: Session) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def assert_course_access(course_id: int, user: User, db: Session) -> Course:
    course = get_course_or_404(course_id, db)
    if user.role == "methodist":
        return course
    assigned = db.scalar(
        select(CourseReviewer.id).where(
            CourseReviewer.course_id == course_id,
            CourseReviewer.user_id == user.id,
        )
    )
    if assigned is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer is not assigned to this course",
        )
    return course


def get_assignment_for_user(
    assignment_id: int,
    user: User,
    db: Session,
    *,
    as_reviewer: bool = False,
) -> Assignment:
    assignment = get_assignment_or_404(assignment_id, db)
    if user.role == "methodist" and not as_reviewer:
        return assignment
    assigned = db.scalar(
        select(AssignmentReviewer.id).where(
            AssignmentReviewer.assignment_id == assignment_id,
            AssignmentReviewer.user_id == user.id,
        )
    )
    if assigned is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer is not assigned to this homework",
        )
    return assignment


def reviewer_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.login


def get_student_enrollment(
    course_id: int, student_id: int, db: Session
) -> EnrollmentApplication | None:
    return db.scalar(
        select(EnrollmentApplication).where(
            EnrollmentApplication.course_id == course_id,
            EnrollmentApplication.user_id == student_id,
        )
    )


def enrolled_count(course_id: int, db: Session) -> int:
    return db.scalar(
        select(func.count(EnrollmentApplication.id)).where(
            EnrollmentApplication.course_id == course_id,
            EnrollmentApplication.status == "enrolled",
        )
    ) or 0


def student_assignment_out(
    assignment: Assignment, student_id: int, db: Session
) -> StudentAssignmentOut:
    submission = db.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.student_user_id == student_id,
        )
    )
    return StudentAssignmentOut(
        id=assignment.id,
        title=assignment.title,
        number=assignment.number,
        deadline=assignment.deadline,
        task_url=assignment.task_url,
        submission=(
            StudentSubmissionOut.model_validate(submission, from_attributes=True)
            if submission
            else None
        ),
    )


def student_course_out(
    course: Course,
    student: User,
    db: Session,
    *,
    include_assignments: bool = False,
) -> StudentCourseOut | StudentCourseDetailOut:
    enrollment = get_student_enrollment(course.id, student.id, db)
    status_value = enrollment.status if enrollment else "none"
    total_points = db.scalar(
        select(func.coalesce(func.sum(Submission.score), 0))
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .where(
            Assignment.course_id == course.id,
            Submission.student_user_id == student.id,
            Submission.status == "reviewed",
        )
    ) or 0
    values = dict(
        id=course.id,
        title=course.title,
        year=course.year,
        cohort=course.cohort,
        stream=course.stream,
        active=course.active,
        cover_color=course.cover_color,
        description=course.description,
        capacity=course.capacity,
        enrolled_count=enrolled_count(course.id, db),
        enrollment_status=status_value,
        total_points=int(total_points),
    )
    if not include_assignments:
        return StudentCourseOut(**values)
    assignments = []
    if status_value == "enrolled":
        items = db.scalars(
            select(Assignment)
            .where(Assignment.course_id == course.id)
            .order_by(Assignment.deadline, Assignment.number, Assignment.id)
        ).all()
        assignments = [
            student_assignment_out(item, student.id, db) for item in items
        ]
    return StudentCourseDetailOut(**values, assignments=assignments)


def enrollment_application_out(
    application: EnrollmentApplication,
) -> EnrollmentApplicationOut:
    return EnrollmentApplicationOut(
        id=application.id,
        course_id=application.course_id,
        course_title=application.course.title,
        student_id=application.user_id,
        student_name=reviewer_name(application.student),
        student_login=application.student.login,
        student_telegram=application.student.telegram,
        status=application.status,
        created_at=application.created_at,
        decided_at=application.decided_at,
    )


@app.post(
    "/api/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> AuthResponse:
    login = payload.login.strip().lower()
    telegram = payload.telegram.strip().removeprefix("@")
    if not telegram:
        raise HTTPException(status_code=422, detail="Telegram username required")
    if db.scalar(select(User.id).where(User.login == login)) is not None:
        raise HTTPException(status_code=409, detail="Login already registered")
    user = User(
        login=login,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        telegram=telegram,
        role=payload.role,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Login already registered") from None
    return create_auth_response(user, db)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(
        select(User).where(User.login == payload.login.strip().lower())
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login or password",
        )
    return create_auth_response(user, db)


@app.get("/api/auth/me", response_model=UserOut)
def auth_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@app.post(
    "/api/student/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_student(
    payload: StudentCreate, db: Session = Depends(get_db)
) -> AuthResponse:
    login_value = payload.login.strip().lower()
    if db.scalar(select(User.id).where(User.login == login_value)) is not None:
        raise HTTPException(status_code=409, detail="Login already registered")
    student = User(
        login=login_value,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        telegram=payload.telegram.strip().removeprefix("@"),
        role="student",
    )
    db.add(student)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Login already registered") from None
    return create_auth_response(student, db)


@app.post("/api/student/auth/login", response_model=AuthResponse)
def login_student(
    payload: LoginRequest, db: Session = Depends(get_db)
) -> AuthResponse:
    student = db.scalar(
        select(User).where(User.login == payload.login.strip().lower())
    )
    if (
        student is None
        or student.role != "student"
        or not verify_password(payload.password, student.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login or password",
        )
    return create_auth_response(student, db)


@app.get("/api/student/auth/me", response_model=UserOut)
def student_me(current_user: User = Depends(require_student)) -> User:
    return current_user


@app.get("/api/student/courses", response_model=list[StudentCourseOut])
def list_student_courses(
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> list[StudentCourseOut]:
    courses = db.scalars(
        select(Course)
        .where(Course.active.is_(True))
        .order_by(Course.year.desc(), Course.stream.desc(), Course.id)
    ).all()
    return [
        StudentCourseOut.model_validate(student_course_out(item, student, db))
        for item in courses
    ]


@app.get("/api/student/courses/mine", response_model=list[StudentCourseOut])
def list_my_student_courses(
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> list[StudentCourseOut]:
    course_ids = select(EnrollmentApplication.course_id).where(
        EnrollmentApplication.user_id == student.id,
        EnrollmentApplication.status == "enrolled",
    )
    courses = db.scalars(
        select(Course)
        .where(Course.id.in_(course_ids))
        .order_by(Course.year.desc(), Course.stream.desc(), Course.id)
    ).all()
    return [
        StudentCourseOut.model_validate(student_course_out(item, student, db))
        for item in courses
    ]


@app.get(
    "/api/student/courses/{course_id}",
    response_model=StudentCourseDetailOut,
)
def get_student_course(
    course_id: int,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> StudentCourseDetailOut:
    course = get_course_or_404(course_id, db)
    return StudentCourseDetailOut.model_validate(
        student_course_out(course, student, db, include_assignments=True)
    )


@app.post(
    "/api/student/courses/{course_id}/apply",
    response_model=EnrollmentApplicationOut,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_course(
    course_id: int,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> EnrollmentApplicationOut:
    course = get_course_or_404(course_id, db)
    if not course.active:
        raise HTTPException(status_code=409, detail="Course is not accepting applications")
    if enrolled_count(course_id, db) >= course.capacity:
        raise HTTPException(status_code=409, detail="Course has no available places")
    application = get_student_enrollment(course_id, student.id, db)
    if application and application.status in {"pending", "enrolled"}:
        raise HTTPException(status_code=409, detail="Application already exists")
    if application is None:
        application = EnrollmentApplication(
            course_id=course_id,
            user_id=student.id,
            status="pending",
        )
        db.add(application)
    else:
        application.status = "pending"
        application.created_at = datetime.now(timezone.utc)
        application.decided_at = None
        application.decided_by_user_id = None
    db.commit()
    application = db.scalar(
        select(EnrollmentApplication)
        .where(EnrollmentApplication.id == application.id)
        .options(
            selectinload(EnrollmentApplication.course),
            selectinload(EnrollmentApplication.student),
        )
    )
    assert application is not None
    return enrollment_application_out(application)


def require_student_enrollment(
    course_id: int, student: User, db: Session
) -> EnrollmentApplication:
    enrollment = get_student_enrollment(course_id, student.id, db)
    if enrollment is None or enrollment.status != "enrolled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student is not enrolled in this course",
        )
    return enrollment


@app.get(
    "/api/student/courses/{course_id}/assignments",
    response_model=list[StudentAssignmentOut],
)
def list_student_assignments(
    course_id: int,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> list[StudentAssignmentOut]:
    require_student_enrollment(course_id, student, db)
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.course_id == course_id)
        .order_by(Assignment.deadline, Assignment.number, Assignment.id)
    ).all()
    return [student_assignment_out(item, student.id, db) for item in assignments]


@app.get(
    "/api/student/assignments/{assignment_id}",
    response_model=StudentAssignmentOut,
)
def get_student_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> StudentAssignmentOut:
    assignment = get_assignment_or_404(assignment_id, db)
    require_student_enrollment(assignment.course_id, student, db)
    return student_assignment_out(assignment, student.id, db)


@app.post(
    "/api/student/assignments/{assignment_id}/submit",
    response_model=StudentSubmissionOut,
)
def submit_student_work(
    assignment_id: int,
    payload: StudentSubmissionCreate,
    db: Session = Depends(get_db),
    student: User = Depends(require_student),
) -> StudentSubmissionOut:
    assignment = get_assignment_or_404(assignment_id, db)
    require_student_enrollment(assignment.course_id, student, db)
    submission = db.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment_id,
            Submission.student_user_id == student.id,
        )
    )
    if submission is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Работа уже отправлена; повторная отправка недоступна",
        )
    submission = Submission(
        assignment_id=assignment_id,
        student_user_id=student.id,
        student_name=reviewer_name(student),
        work_url=payload.work_url,
        stepik_url="",
        status="pending",
        source_type="github" if "github.com" in payload.work_url.lower() else "url",
        evaluation_status="not_requested",
    )
    db.add(submission)
    db.flush()
    assign_new_submission(submission, assignment_id, db)
    db.commit()
    db.refresh(submission)
    return StudentSubmissionOut.model_validate(submission, from_attributes=True)


@app.get(
    "/api/enrollment-applications",
    response_model=list[EnrollmentApplicationOut],
)
def list_enrollment_applications(
    application_status: Literal["pending", "enrolled", "rejected"] = Query(
        default="pending", alias="status"
    ),
    course_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> list[EnrollmentApplicationOut]:
    query = (
        select(EnrollmentApplication)
        .where(EnrollmentApplication.status == application_status)
        .options(
            selectinload(EnrollmentApplication.course),
            selectinload(EnrollmentApplication.student),
        )
        .order_by(EnrollmentApplication.created_at, EnrollmentApplication.id)
    )
    if course_id is not None:
        get_course_or_404(course_id, db)
        query = query.where(EnrollmentApplication.course_id == course_id)
    applications = db.scalars(query).all()
    return [enrollment_application_out(item) for item in applications]


@app.patch(
    "/api/enrollment-applications/{application_id}",
    response_model=EnrollmentApplicationOut,
)
def decide_enrollment_application(
    application_id: int,
    payload: EnrollmentDecision,
    db: Session = Depends(get_db),
    methodist: User = Depends(require_methodist),
) -> EnrollmentApplicationOut:
    application = db.scalar(
        select(EnrollmentApplication)
        .where(EnrollmentApplication.id == application_id)
        .options(
            selectinload(EnrollmentApplication.course),
            selectinload(EnrollmentApplication.student),
        )
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status != "pending":
        raise HTTPException(status_code=409, detail="Application is already decided")
    if (
        payload.status == "enrolled"
        and enrolled_count(application.course_id, db) >= application.course.capacity
    ):
        raise HTTPException(status_code=409, detail="Course has no available places")
    application.status = payload.status
    application.decided_at = datetime.now(timezone.utc)
    application.decided_by_user_id = methodist.id
    db.commit()
    db.refresh(application)
    return enrollment_application_out(application)


@app.get("/api/courses", response_model=list[CourseOut])
def list_courses(
    active: bool | None = Query(default=None),
    as_reviewer: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CourseOut]:
    query = select(Course).options(
        selectinload(Course.assignments),
        selectinload(Course.enrollment_applications),
    )
    if current_user.role == "reviewer" or as_reviewer:
        assigned = select(CourseReviewer.course_id).where(
            CourseReviewer.user_id == current_user.id
        )
        query = query.where(Course.id.in_(assigned))
    if active is not None:
        query = query.where(Course.active == active)
    courses = db.scalars(
        query.order_by(Course.year.desc(), Course.stream.desc())
    ).all()
    return [serialize_course(course) for course in courses]


@app.get("/api/reviewers", response_model=list[UserOut])
def list_reviewer_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_methodist),
) -> list[User]:
    reviewers = list(
        db.scalars(
            select(User)
            .where(User.role == "reviewer")
            .order_by(User.last_name, User.first_name, User.id)
        ).all()
    )
    if all(user.id != current_user.id for user in reviewers):
        reviewers.insert(0, current_user)
    return reviewers


@app.get("/api/courses/{course_id}/reviewers", response_model=list[CourseReviewerOut])
def list_course_reviewers(
    course_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> list[CourseReviewerOut]:
    get_course_or_404(course_id, db)
    links = db.scalars(
        select(CourseReviewer)
        .where(CourseReviewer.course_id == course_id)
        .options(selectinload(CourseReviewer.user))
        .order_by(CourseReviewer.id)
    ).all()
    return [serialize_course_reviewer(link) for link in links]


@app.post(
    "/api/courses/{course_id}/reviewers",
    response_model=CourseReviewerOut,
    status_code=status.HTTP_201_CREATED,
)
def add_course_reviewer(
    course_id: int,
    payload: CourseReviewerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_methodist),
) -> CourseReviewerOut:
    get_course_or_404(course_id, db)
    reviewer = db.get(User, payload.user_id)
    can_assign = reviewer is not None and (
        reviewer.role == "reviewer" or reviewer.id == current_user.id
    )
    if not can_assign:
        raise HTTPException(status_code=404, detail="Reviewer account not found")
    link = CourseReviewer(course_id=course_id, user_id=reviewer.id)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer is already assigned to this course",
        ) from None
    db.refresh(link)
    link.user = reviewer
    return serialize_course_reviewer(link)


@app.delete(
    "/api/courses/{course_id}/reviewers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_course_reviewer(
    course_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> Response:
    get_course_or_404(course_id, db)
    link = db.scalar(
        select(CourseReviewer).where(
            CourseReviewer.course_id == course_id,
            CourseReviewer.user_id == user_id,
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Reviewer is not assigned to this course")
    assignment_ids = list(
        db.scalars(
            select(Assignment.id).where(Assignment.course_id == course_id)
        ).all()
    )
    homework_links = list(
        db.scalars(
            select(AssignmentReviewer).where(
                AssignmentReviewer.assignment_id.in_(assignment_ids),
                AssignmentReviewer.user_id == user_id,
            )
        ).all()
    ) if assignment_ids else []
    for homework_link in homework_links:
        db.delete(homework_link)
    db.delete(link)
    db.flush()
    for assignment_id in assignment_ids:
        rebalance_assignment_submissions(assignment_id, db)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> CourseOut:
    course = Course(
        title=payload.title.strip(),
        year=payload.year,
        cohort=payload.cohort.strip(),
        stream=payload.stream,
        active=payload.active,
        cover_color=payload.cover_color.strip(),
        students_count=payload.students_count,
        description=payload.description.strip(),
        capacity=payload.capacity,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    course.assignments = []
    course.enrollment_applications = []
    return serialize_course(course)


@app.patch("/api/courses/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CourseOut:
    course = assert_course_access(course_id, current_user, db)
    course.description = payload.description.strip()
    db.commit()
    course = db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.assignments),
            selectinload(Course.enrollment_applications),
        )
    )
    assert course is not None
    return serialize_course(course)


@app.post(
    "/api/courses/{course_id}/assignments",
    response_model=AssignmentListOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment(
    course_id: int,
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> AssignmentListOut:
    get_course_or_404(course_id, db)
    next_number = db.scalar(
        select(func.max(Assignment.number)).where(Assignment.course_id == course_id)
    )
    assignment = Assignment(
        course_id=course_id,
        title=payload.title.strip(),
        number=payload.number or (next_number or 0) + 1,
        deadline=payload.deadline,
        task_url=payload.task_url.strip(),
        criteria_url=payload.criteria_url.strip(),
        criteria=[item.model_dump() for item in payload.criteria],
        reviewer_guide=payload.reviewer_guide.strip(),
    )
    db.add(assignment)
    db.flush()
    for user_id in dict.fromkeys(payload.reviewer_user_ids):
        attach_homework_reviewer(assignment, user_id, db)
    rebalance_assignment_submissions(assignment.id, db)
    db.commit()
    db.refresh(assignment)
    return AssignmentListOut(
        id=assignment.id,
        title=assignment.title,
        number=assignment.number,
        deadline=assignment.deadline,
        task_url=assignment.task_url,
        criteria_url=assignment.criteria_url,
        total=0,
        reviewed=0,
        reviewer_checked=0,
        reviewer_total=0,
    )


@app.post("/api/assignments/{assignment_id}/task-file", response_model=AssignmentOut)
def upload_assignment_task_file(
    assignment_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> AssignmentOut:
    logger.info("task.upload.started assignment_id=%s filename=%s", assignment_id, file.filename)
    assignment = get_assignment_or_404(assignment_id, db)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_TASK_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Поддерживаются PDF, DOCX, XLSX и Markdown")
    storage = Path(os.getenv("STORAGE_DIR", "./storage")) / "tasks"
    storage.mkdir(parents=True, exist_ok=True)
    destination = storage / f"assignment-{assignment.id}{suffix}"
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Файл задания пуст")
    destination.write_bytes(content)
    try:
        task_text = extract_task_text(destination)
        fallback = fallback_rubric(str(assignment.id), assignment.title, task_text, assignment.criteria)
        try:
            rubric = asyncio.run(
                LLMService(PipelineSettings.from_environment()).parse_rubric(
                    str(assignment.id), assignment.title, task_text, fallback
                )
            )
            assignment.rubric_status = "completed"
        except Exception:
            rubric = fallback
            assignment.rubric_status = "fallback"
    except Exception as exc:
        destination.unlink(missing_ok=True)
        assignment.rubric_status = "failed"
        db.commit()
        raise HTTPException(status_code=422, detail=f"Не удалось разобрать задание: {exc}") from exc
    assignment.task_file_path = str(destination)
    assignment.task_text = task_text
    assignment.rubric_json = rubric.model_dump(mode="json")
    assignment.criteria = [
        {"title": item.name, "description": item.description, "max_score": item.max_points}
        for item in rubric.criteria
    ]
    assignment.criteria_version += 1
    for submission in assignment.submissions:
        if submission.evaluation_status == "completed":
            submission.evaluation_status = "stale"
    db.commit()
    db.refresh(assignment)
    logger.info("task.rubric.persisted assignment_id=%s status=%s criteria_version=%s", assignment.id, assignment.rubric_status, assignment.criteria_version)
    return AssignmentOut(
        id=assignment.id,
        course_id=assignment.course_id,
        title=assignment.title,
        number=assignment.number,
        deadline=assignment.deadline,
        task_url=assignment.task_url,
        criteria_url=assignment.criteria_url,
        criteria=assignment.criteria,
        reviewer_guide=assignment.reviewer_guide,
        submissions=[SubmissionOut.model_validate(item) for item in assignment.submissions],
    )


@app.get("/api/courses/{course_id}/assignments", response_model=list[AssignmentListOut])
def list_assignments(
    course_id: int,
    as_reviewer: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AssignmentListOut]:
    assert_course_access(course_id, current_user, db)
    query = (
        select(Assignment)
        .where(Assignment.course_id == course_id)
        .options(
            selectinload(Assignment.submissions),
            selectinload(Assignment.reviewers),
        )
        .order_by(Assignment.number, Assignment.id)
    )
    reviewer_view = current_user.role == "reviewer" or as_reviewer
    if reviewer_view:
        assigned = select(AssignmentReviewer.assignment_id).where(
            AssignmentReviewer.user_id == current_user.id
        )
        query = query.where(Assignment.id.in_(assigned))
    assignments = db.scalars(query).all()
    result = []
    for item in assignments:
        current_reviewer = next(
            (reviewer for reviewer in item.reviewers if reviewer.user_id == current_user.id),
            None,
        )
        reviewer_submissions = [
            submission
            for submission in item.submissions
            if submission.reviewer_user_id == current_user.id
        ]
        result.append(
            AssignmentListOut(
                id=item.id,
                title=item.title,
                number=item.number,
                deadline=item.deadline,
                task_url=item.task_url,
                criteria_url=item.criteria_url,
                total=len(item.submissions),
                reviewed=sum(
                    submission.status == "reviewed"
                    for submission in item.submissions
                ),
                reviewer_checked=sum(
                    submission.status == "reviewed"
                    for submission in reviewer_submissions
                ) if current_reviewer is None else current_reviewer.checked,
                reviewer_total=(
                    len(reviewer_submissions)
                    if current_reviewer is None
                    else current_reviewer.total
                ),
            )
        )
    return result


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
def get_assignment(
    assignment_id: int,
    as_reviewer: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssignmentOut:
    assignment = get_assignment_for_user(
        assignment_id, current_user, db, as_reviewer=as_reviewer
    )
    submissions = assignment.submissions
    if current_user.role == "reviewer" or as_reviewer:
        submissions = [
            item
            for item in assignment.submissions
            if item.reviewer_user_id == current_user.id
        ]
    return AssignmentOut(
        id=assignment.id,
        course_id=assignment.course_id,
        title=assignment.title,
        number=assignment.number,
        deadline=assignment.deadline,
        task_url=assignment.task_url,
        criteria_url=assignment.criteria_url,
        criteria=assignment.criteria,
        reviewer_guide=assignment.reviewer_guide,
        submissions=[SubmissionOut.model_validate(item) for item in submissions],
    )


@app.put("/api/assignments/{assignment_id}/criteria", response_model=AssignmentOut)
def update_criteria(
    assignment_id: int,
    payload: CriteriaUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> AssignmentOut:
    assignment = get_assignment_or_404(assignment_id, db)
    assignment.criteria = [item.model_dump() for item in payload.criteria]
    assignment.reviewer_guide = payload.reviewer_guide
    assignment.criteria_version += 1
    for submission in assignment.submissions:
        if submission.evaluation_status == "completed":
            submission.evaluation_status = "stale"
    db.commit()
    return AssignmentOut(
        id=assignment.id,
        course_id=assignment.course_id,
        title=assignment.title,
        number=assignment.number,
        deadline=assignment.deadline,
        task_url=assignment.task_url,
        criteria_url=assignment.criteria_url,
        criteria=assignment.criteria,
        reviewer_guide=assignment.reviewer_guide,
        submissions=[SubmissionOut.model_validate(item) for item in assignment.submissions],
    )


@app.get(
    "/api/assignments/{assignment_id}/reviewers",
    response_model=list[AssignmentReviewerOut],
)
def list_assignment_reviewers(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> list[AssignmentReviewer]:
    get_assignment_or_404(assignment_id, db)
    return list(
        db.scalars(
            select(AssignmentReviewer)
            .where(AssignmentReviewer.assignment_id == assignment_id)
            .order_by(AssignmentReviewer.id)
        ).all()
    )


def attach_homework_reviewer(
    assignment: Assignment,
    user_id: int,
    db: Session,
) -> AssignmentReviewer:
    enrolled = db.scalar(
        select(CourseReviewer)
        .where(
            CourseReviewer.course_id == assignment.course_id,
            CourseReviewer.user_id == user_id,
        )
        .options(selectinload(CourseReviewer.user))
    )
    if enrolled is None:
        raise HTTPException(
            status_code=404,
            detail="Reviewer is not assigned to this course",
        )
    existing = db.scalar(
        select(AssignmentReviewer).where(
            AssignmentReviewer.assignment_id == assignment.id,
            AssignmentReviewer.user_id == user_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer is already assigned to this homework",
        )
    user = enrolled.user
    by_telegram = db.scalar(
        select(AssignmentReviewer).where(
            AssignmentReviewer.assignment_id == assignment.id,
            AssignmentReviewer.telegram == user.telegram,
            AssignmentReviewer.user_id.is_(None),
        )
    )
    if by_telegram is not None:
        by_telegram.user_id = user.id
        by_telegram.name = f"{user.first_name} {user.last_name}".strip() or user.login
        return by_telegram
    reviewer = AssignmentReviewer(
        assignment_id=assignment.id,
        user_id=user.id,
        name=f"{user.first_name} {user.last_name}".strip() or user.login,
        telegram=user.telegram,
        total=len(assignment.submissions),
    )
    db.add(reviewer)
    db.flush()
    return reviewer


@app.post(
    "/api/assignments/{assignment_id}/reviewers",
    response_model=AssignmentReviewerOut,
    status_code=status.HTTP_201_CREATED,
)
def add_assignment_reviewer(
    assignment_id: int,
    payload: AssignmentReviewerCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> AssignmentReviewer:
    assignment = get_assignment_or_404(assignment_id, db)
    reviewer = attach_homework_reviewer(assignment, payload.user_id, db)
    rebalance_assignment_submissions(assignment.id, db)
    db.commit()
    db.refresh(reviewer)
    return reviewer


@app.post(
    "/api/assignments/{assignment_id}/reviewers/bulk",
    response_model=list[AssignmentReviewerOut],
)
def add_assignment_reviewers_bulk(
    assignment_id: int,
    payload: AssignmentReviewersBulkCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> list[AssignmentReviewer]:
    assignment = get_assignment_or_404(assignment_id, db)
    existing_ids = set(
        db.scalars(
            select(AssignmentReviewer.user_id).where(
                AssignmentReviewer.assignment_id == assignment_id,
                AssignmentReviewer.user_id.is_not(None),
            )
        ).all()
    )
    added = [
        attach_homework_reviewer(assignment, user_id, db)
        for user_id in dict.fromkeys(payload.user_ids)
        if user_id not in existing_ids
    ]
    rebalance_assignment_submissions(assignment.id, db)
    db.commit()
    for reviewer in added:
        db.refresh(reviewer)
    return added


@app.delete(
    "/api/assignments/{assignment_id}/reviewers/{reviewer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_assignment_reviewer(
    assignment_id: int,
    reviewer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> Response:
    reviewer = db.scalar(
        select(AssignmentReviewer).where(
            AssignmentReviewer.id == reviewer_id,
            AssignmentReviewer.assignment_id == assignment_id,
        )
    )
    if reviewer is None:
        raise HTTPException(status_code=404, detail="Reviewer not found")
    db.delete(reviewer)
    db.flush()
    rebalance_assignment_submissions(assignment_id, db)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission_detail(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubmissionOut:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    get_assignment_for_user(submission.assignment_id, current_user, db)
    if (
        current_user.role == "reviewer"
        and submission.reviewer_user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Submission is assigned to another reviewer",
        )
    return submission_out_with_evaluation(submission, db)


def submission_out_with_evaluation(submission: Submission, db: Session) -> SubmissionOut:
    output = SubmissionOut.model_validate(submission)
    evaluation_id = submission.latest_evaluation_id
    evaluation = db.get(Evaluation, evaluation_id) if evaluation_id else None
    if evaluation is None:
        evaluation = db.scalar(
            select(Evaluation)
            .where(Evaluation.submission_id == submission.id)
            .order_by(Evaluation.id.desc())
        )
    if evaluation is not None:
        output.latest_evaluation_id = evaluation.id
        output.review_json = evaluation.review_json
        output.ai_assessment_json = evaluation.ai_assessment_json
        output.pdf_report_path = evaluation.pdf_report_path
    return output


@app.post("/api/submissions/{submission_id}/ai-draft", response_model=SubmissionOut)
def create_ai_draft(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Submission:
    logger.info("evaluation.enqueue.requested submission_id=%s user_id=%s", submission_id, current_user.id)
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    get_assignment_for_user(submission.assignment_id, current_user, db)
    if (
        current_user.role == "reviewer"
        and submission.reviewer_user_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Submission is assigned to another reviewer")

    if submission.evaluation_status in {"queued", "processing"}:
        return submission_out_with_evaluation(submission, db)
    if not submission.work_url and not submission.source_file_path:
        raise HTTPException(status_code=422, detail="У работы отсутствует источник для AI-проверки")
    submission.source_type = "file" if submission.source_file_path else "github"
    submission.evaluation_status = "queued"
    submission.status = "in_review"
    submission.reviewer = submission.reviewer or reviewer_name(current_user)
    submission.reviewer_user_id = submission.reviewer_user_id or current_user.id
    db.commit()
    db.refresh(submission)
    try:
        evaluate_submission_task.apply_async(args=[submission.id], ignore_result=True)
        logger.info("evaluation.enqueue.accepted submission_id=%s", submission.id)
    except Exception:
        submission.evaluation_status = "failed"
        db.commit()
        logger.exception("evaluation.enqueue.failed submission_id=%s", submission.id)
    return submission_out_with_evaluation(submission, db)


@app.put("/api/submissions/{submission_id}/review", response_model=SubmissionOut)
def save_review(
    submission_id: int,
    payload: ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    get_assignment_for_user(submission.assignment_id, current_user, db)
    if (
        current_user.role == "reviewer"
        and submission.reviewer_user_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Submission is assigned to another reviewer")
    assignment = get_assignment_or_404(submission.assignment_id, db)
    if len(payload.criterion_scores) != len(assignment.criteria):
        raise HTTPException(
            status_code=422,
            detail="Нужно выставить оценку по каждому критерию",
        )
    provided_indexes = {item.criterion_index for item in payload.criterion_scores}
    if provided_indexes != set(range(len(assignment.criteria))):
        raise HTTPException(status_code=422, detail="Некорректный набор критериев")
    criterion_scores = []
    for item in sorted(payload.criterion_scores, key=lambda value: value.criterion_index):
        criterion = assignment.criteria[item.criterion_index]
        if item.score > criterion["max_score"]:
            raise HTTPException(
                status_code=422,
                detail=f"Оценка по критерию «{criterion['title']}» превышает максимум",
            )
        criterion_scores.append(
            {
                "criterion_index": item.criterion_index,
                "criterion": criterion["title"],
                "score": item.score,
                "max_score": criterion["max_score"],
                "comment": item.comment.strip(),
            }
        )
    current_reviewer_name = submission.reviewer or reviewer_name(current_user)
    submission.score = sum(item["score"] for item in criterion_scores)
    submission.criterion_scores = criterion_scores
    submission.summary = payload.summary
    submission.integrity_flag = payload.integrity_flag
    submission.status = "reviewed"
    submission.reviewer = current_reviewer_name
    submission.reviewer_user_id = current_user.id
    recount_reviewer_stats(submission.assignment_id, db)
    db.commit()
    db.refresh(submission)
    return submission


@app.get("/api/assignments/{assignment_id}/next", response_model=SubmissionOut)
def next_submission(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Submission:
    get_assignment_for_user(assignment_id, current_user, db)
    submission = db.scalar(
        select(Submission)
        .where(
            Submission.assignment_id == assignment_id,
            Submission.reviewer_user_id == current_user.id,
            Submission.status.in_(["pending", "in_review"]),
        )
        .order_by(Submission.status.desc(), Submission.id)
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="No submissions left")
    if submission.status == "pending":
        submission.status = "in_review"
        submission.reviewer = reviewer_name(current_user)
        submission.reviewer_user_id = current_user.id
        db.commit()
        db.refresh(submission)
    return submission


def _xlsx_file_response(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _read_xlsx_upload(file: UploadFile) -> bytes:
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")
    return content


def _users_by_login(db: Session) -> dict[str, User]:
    return {user.login.lower(): user for user in db.scalars(select(User)).all()}


def _format_dt(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


@app.get("/api/courses/{course_id}/export.xlsx")
def export_course_xlsx(
    course_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> Response:
    course = get_course_or_404(course_id, db)
    applications = list(
        db.scalars(
            select(EnrollmentApplication)
            .where(EnrollmentApplication.course_id == course_id)
            .options(selectinload(EnrollmentApplication.student))
            .order_by(EnrollmentApplication.id)
        ).all()
    )
    reviewers = list(
        db.scalars(
            select(CourseReviewer)
            .where(CourseReviewer.course_id == course_id)
            .options(selectinload(CourseReviewer.user))
            .order_by(CourseReviewer.id)
        ).all()
    )
    content = export_course_workbook(
        students=[
            [
                item.student.login,
                item.student.first_name,
                item.student.last_name,
                item.student.telegram,
                item.status,
            ]
            for item in applications
            if item.status == "enrolled"
        ],
        reviewers=[
            [
                item.user.login,
                item.user.first_name,
                item.user.last_name,
                item.user.telegram,
            ]
            for item in reviewers
        ],
        applications=[
            [
                item.student.login,
                item.student.first_name,
                item.student.last_name,
                item.student.telegram,
                item.status,
                _format_dt(item.created_at),
                _format_dt(item.decided_at),
            ]
            for item in applications
        ],
    )
    return _xlsx_file_response(content, f"course-{course.id}.xlsx")


@app.post(
    "/api/courses/{course_id}/reviewers/import",
    response_model=XlsxImportResult,
)
def import_course_reviewers(
    course_id: int,
    confirm: bool = Query(default=False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_methodist),
) -> XlsxImportResult:
    get_course_or_404(course_id, db)
    rows, errors = parse_logins(_read_xlsx_upload(file))
    users = _users_by_login(db)
    assigned_ids = set(
        db.scalars(
            select(CourseReviewer.user_id).where(CourseReviewer.course_id == course_id)
        ).all()
    )
    added: list[str] = []
    skipped: list[str] = []
    to_assign: list[User] = []
    for row_number, login in rows:
        user = users.get(login.lower())
        if user is None:
            errors.append(f"Строка {row_number}: неизвестный логин {login}")
            continue
        if user.role not in {"reviewer", "methodist"}:
            errors.append(f"Строка {row_number}: {login} не является ревьюером")
            continue
        if user.role == "methodist" and user.id != current_user.id:
            errors.append(f"Строка {row_number}: {login} нельзя назначить на курс")
            continue
        if user.id in assigned_ids:
            skipped.append(login)
            continue
        added.append(login)
        to_assign.append(user)
        assigned_ids.add(user.id)
    if confirm:
        for user in to_assign:
            db.add(CourseReviewer(course_id=course_id, user_id=user.id))
        db.commit()
    return XlsxImportResult(
        added=added,
        skipped=skipped,
        errors=errors,
        applied=confirm,
    )


@app.get("/api/assignments/{assignment_id}/export.xlsx")
def export_assignment_xlsx(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> Response:
    assignment = get_assignment_or_404(assignment_id, db)
    submissions = list(
        db.scalars(
            select(Submission)
            .where(Submission.assignment_id == assignment_id)
            .options(
                selectinload(Submission.student),
                selectinload(Submission.reviewer_user),
            )
            .order_by(Submission.id)
        ).all()
    )
    reviewers = list(
        db.scalars(
            select(AssignmentReviewer)
            .where(AssignmentReviewer.assignment_id == assignment_id)
            .options(selectinload(AssignmentReviewer.user))
            .order_by(AssignmentReviewer.id)
        ).all()
    )
    score_rows: list[list[object]] = []
    for submission in submissions:
        student_login = submission.student.login if submission.student else ""
        for item in submission.criterion_scores or []:
            score_rows.append(
                [
                    submission.student_name,
                    student_login,
                    item.get("criterion", ""),
                    item.get("score", ""),
                    item.get("max_score", ""),
                    item.get("comment", ""),
                    submission.score or "",
                ]
            )
    content = export_assignment_workbook(
        submissions=[
            [
                item.student_name,
                item.student.login if item.student else "",
                item.work_url,
                item.status,
                item.reviewer or "",
                item.reviewer_user.login if item.reviewer_user else "",
                item.score if item.score is not None else "",
                item.summary or "",
            ]
            for item in submissions
        ],
        reviewers=[
            [
                item.user.login if item.user else "",
                item.name,
                item.telegram,
                item.checked,
                item.total,
            ]
            for item in reviewers
        ],
        scores=score_rows,
    )
    return _xlsx_file_response(content, f"assignment-{assignment.id}.xlsx")


@app.post(
    "/api/assignments/{assignment_id}/reviewers/import",
    response_model=XlsxImportResult,
)
def import_assignment_reviewers(
    assignment_id: int,
    confirm: bool = Query(default=False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> XlsxImportResult:
    assignment = get_assignment_or_404(assignment_id, db)
    rows, errors = parse_logins(_read_xlsx_upload(file))
    users = _users_by_login(db)
    course_reviewer_ids = set(
        db.scalars(
            select(CourseReviewer.user_id).where(
                CourseReviewer.course_id == assignment.course_id
            )
        ).all()
    )
    assigned_ids = set(
        db.scalars(
            select(AssignmentReviewer.user_id).where(
                AssignmentReviewer.assignment_id == assignment_id,
                AssignmentReviewer.user_id.is_not(None),
            )
        ).all()
    )
    added: list[str] = []
    skipped: list[str] = []
    to_assign: list[int] = []
    for row_number, login in rows:
        user = users.get(login.lower())
        if user is None:
            errors.append(f"Строка {row_number}: неизвестный логин {login}")
            continue
        if user.id not in course_reviewer_ids:
            errors.append(
                f"Строка {row_number}: {login} не назначен на курс"
            )
            continue
        if user.id in assigned_ids:
            skipped.append(login)
            continue
        added.append(login)
        to_assign.append(user.id)
        assigned_ids.add(user.id)
    if confirm:
        for user_id in to_assign:
            attach_homework_reviewer(assignment, user_id, db)
        rebalance_assignment_submissions(assignment.id, db)
        db.commit()
    return XlsxImportResult(
        added=added,
        skipped=skipped,
        errors=errors,
        applied=confirm,
    )


@app.get("/api/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> dict:
    submissions = db.scalars(select(Submission)).all()
    clarifications = db.scalars(
        select(ClarificationRequest).order_by(ClarificationRequest.created_at.desc())
    ).all()
    reviewer_rows = db.scalars(
        select(AssignmentReviewer).order_by(AssignmentReviewer.id)
    ).all()
    reviewer_totals: dict[tuple[int | None, str, str], dict] = {}
    for reviewer in reviewer_rows:
        key = (reviewer.user_id, reviewer.name, reviewer.telegram)
        aggregate = reviewer_totals.setdefault(
            key,
            {
                "id": reviewer.user_id or reviewer.id,
                "name": reviewer.name,
                "telegram": reviewer.telegram,
                "checked": 0,
                "total": 0,
                "anomaly": False,
                "user_id": reviewer.user_id,
            },
        )
        aggregate["checked"] += reviewer.checked
        aggregate["total"] += reviewer.total
        aggregate["anomaly"] = aggregate["anomaly"] or reviewer.anomaly
    reviewed = [item for item in submissions if item.status == "reviewed"]
    return {
        "total": len(submissions),
        "reviewed": len(reviewed),
        "in_progress": sum(item.status == "in_review" for item in submissions),
        "reviewers": list(reviewer_totals.values()),
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
    current_user: User = Depends(get_current_user),
) -> ClarificationRequest:
    get_assignment_for_user(assignment_id, current_user, db)
    request = ClarificationRequest(
        assignment_id=assignment_id,
        author=reviewer_name(current_user),
        message=payload.message,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@app.patch("/api/clarifications/{clarification_id}", response_model=ClarificationOut)
def update_clarification(
    clarification_id: int,
    payload: ClarificationUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> ClarificationRequest:
    clarification = db.get(ClarificationRequest, clarification_id)
    if clarification is None:
        raise HTTPException(status_code=404, detail="Clarification not found")
    clarification.status = payload.status
    db.commit()
    db.refresh(clarification)
    return clarification


@app.post("/api/assignments/{assignment_id}/deadline-reminder")
def enqueue_deadline_reminder(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_methodist),
) -> dict[str, str]:
    assignment = get_assignment_or_404(assignment_id, db)
    task = deadline_reminder.delay(
        assignment.course.title,
        assignment.title,
        assignment.deadline.isoformat(),
    )
    return {"status": "queued", "task_id": task.id}


@app.get("/api/submissions/{submission_id}/report.pdf")
def download_report(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission.evaluation_status != "completed":
        raise HTTPException(status_code=404, detail="Completed review not found")
    get_assignment_for_user(submission.assignment_id, current_user, db)
    if (
        current_user.role == "reviewer"
        and submission.reviewer_user_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Submission is assigned to another reviewer")

    evaluation = db.get(Evaluation, submission.latest_evaluation_id) if submission.latest_evaluation_id else None
    if evaluation is None:
        evaluation = db.scalar(
            select(Evaluation)
            .where(Evaluation.submission_id == submission.id, Evaluation.status == "completed")
            .order_by(Evaluation.id.desc())
        )
    if evaluation is None or not evaluation.pdf_report_path:
        raise HTTPException(status_code=404, detail="PDF report not found")
    report_path = Path(evaluation.pdf_report_path)
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="PDF report not found")
    return FileResponse(
        report_path,
        media_type="application/pdf",
        filename=f"review-{submission_id}.pdf",
    )
