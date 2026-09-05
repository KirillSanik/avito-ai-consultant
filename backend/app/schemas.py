from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Role = Literal["reviewer", "methodist", "student"]
StaffRole = Literal["reviewer", "methodist"]


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=4, max_length=200)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    telegram: str = Field(min_length=1, max_length=120)
    role: StaffRole


class LoginRequest(BaseModel):
    login: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    first_name: str
    last_name: str
    telegram: str
    role: Role


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class CourseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    year: int = Field(ge=2000, le=2100)
    cohort: str = Field(min_length=2, max_length=80)
    stream: int = Field(ge=1, le=99)
    active: bool = True
    cover_color: str = Field(default="#2563EB", min_length=4, max_length=40)
    students_count: int = Field(default=0, ge=0)
    description: str = Field(default="", max_length=5000)
    capacity: int = Field(default=30, ge=1, le=10000)


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    year: int
    cohort: str
    stream: int
    active: bool
    cover_color: str
    students_count: int
    assignments_count: int = 0
    description: str = ""
    capacity: int = 30
    enrolled_count: int = 0


class CourseUpdate(BaseModel):
    description: str = Field(max_length=5000)


class CourseReviewerCreate(BaseModel):
    user_id: int


class CourseReviewerOut(BaseModel):
    id: int
    user_id: int
    login: str
    first_name: str
    last_name: str
    telegram: str


class Criterion(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    max_score: int = Field(ge=0, le=100)
    description: str = Field(default="", max_length=2000)


def ensure_criteria_total(criteria: list[Criterion]) -> None:
    total = sum(item.max_score for item in criteria)
    if total != 100:
        raise ValueError("Сумма баллов критериев должна быть ровно 100")


class AssignmentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    deadline: datetime
    task_url: str = Field(min_length=8, max_length=500)
    criteria_url: str = Field(default="", max_length=500)
    number: int | None = Field(default=None, ge=1)
    criteria: list[Criterion] = Field(
        default_factory=lambda: [Criterion(title="Качество работы", max_score=100, description="")],
        min_length=1,
    )
    reviewer_guide: str = Field(
        default="Проверьте работу по критериям. AI-оценка является только черновиком.",
        min_length=3,
        max_length=5000,
    )
    reviewer_user_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_criteria_total(self) -> "AssignmentCreate":
        ensure_criteria_total(self.criteria)
        return self


class AssignmentListOut(BaseModel):
    id: int
    title: str
    number: int
    deadline: datetime
    task_url: str
    criteria_url: str
    total: int
    reviewed: int
    reviewer_checked: int
    reviewer_total: int


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_name: str
    work_url: str
    stepik_url: str
    status: str
    reviewer: str | None
    score: int | None
    summary: str | None
    integrity_flag: str | None
    ai_draft: dict | None
    criterion_scores: list[dict] | None
    reviewer_user_id: int | None
    source_type: str = "url"
    source_file_path: str | None = None
    evaluation_status: str = "not_requested"
    latest_evaluation_id: int | None = None
    review_json: dict | None = None
    ai_assessment_json: dict | None = None
    pdf_report_path: str | None = None
    evaluation_error: str | None = None
    has_pdf: bool = False


class AssignmentOut(BaseModel):
    id: int
    course_id: int
    title: str
    number: int
    deadline: datetime
    task_url: str
    criteria_url: str
    criteria: list[Criterion]
    reviewer_guide: str
    submissions: list[SubmissionOut]
    task_file_path: str | None = None
    rubric_json: dict | None = None
    task_text: str | None = None
    rubric_status: str = "not_requested"
    criteria_version: int = 1


class CriterionScoreInput(BaseModel):
    criterion_index: int = Field(ge=0)
    score: int = Field(ge=0, le=100)
    comment: str = Field(default="", max_length=2000)


class ReviewUpdate(BaseModel):
    criterion_scores: list[CriterionScoreInput] = Field(min_length=1)
    summary: str = Field(min_length=3, max_length=3000)
    integrity_flag: str | None = Field(default=None, max_length=1000)


class CriteriaUpdate(BaseModel):
    criteria: list[Criterion] = Field(min_length=1)
    reviewer_guide: str = Field(min_length=3, max_length=5000)

    @model_validator(mode="after")
    def validate_criteria_total(self) -> "CriteriaUpdate":
        ensure_criteria_total(self.criteria)
        return self


class ClarificationCreate(BaseModel):
    message: str = Field(min_length=5, max_length=2000)


class ClarificationUpdate(BaseModel):
    status: Literal["accepted", "rejected", "dismissed"]


class ClarificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    assignment_id: int
    author: str
    message: str
    status: str
    created_at: datetime


class AssignmentReviewerCreate(BaseModel):
    user_id: int


class AssignmentReviewersBulkCreate(BaseModel):
    user_ids: list[int] = Field(min_length=1)


class AssignmentReviewerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    telegram: str
    checked: int
    total: int
    anomaly: bool
    user_id: int | None = None


EnrollmentStatus = Literal["none", "pending", "enrolled", "rejected"]


class StudentCreate(BaseModel):
    login: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=4, max_length=200)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    telegram: str = Field(default="", max_length=120)


class StudentSubmissionCreate(BaseModel):
    work_url: str = Field(min_length=12, max_length=500)

    @field_validator("work_url")
    @classmethod
    def validate_work_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        allowed = ("github.com", "drive.google.com", "docs.google.com")
        if parsed.scheme != "https" or not any(
            host == item or host.endswith(f".{item}") for item in allowed
        ):
            raise ValueError(
                "Разрешены только HTTPS-ссылки GitHub или Google Drive"
            )
        return value.strip()


class StudentSubmissionOut(BaseModel):
    id: int
    work_url: str
    status: str
    score: int | None
    summary: str | None


class StudentAssignmentOut(BaseModel):
    id: int
    title: str
    number: int
    deadline: datetime
    task_url: str
    submission: StudentSubmissionOut | None = None


class StudentCourseOut(BaseModel):
    id: int
    title: str
    year: int
    cohort: str
    stream: int
    active: bool
    cover_color: str
    description: str
    capacity: int
    enrolled_count: int
    enrollment_status: EnrollmentStatus
    total_points: int = 0


class StudentCourseDetailOut(StudentCourseOut):
    assignments: list[StudentAssignmentOut] = Field(default_factory=list)


class EnrollmentApplicationOut(BaseModel):
    id: int
    course_id: int
    course_title: str
    student_id: int
    student_name: str
    student_login: str
    student_telegram: str
    status: Literal["pending", "enrolled", "rejected"]
    created_at: datetime
    decided_at: datetime | None


class EnrollmentDecision(BaseModel):
    status: Literal["enrolled", "rejected"]


class XlsxImportResult(BaseModel):
    added: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    applied: bool = False
