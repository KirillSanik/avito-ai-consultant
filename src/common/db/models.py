"""SQLAlchemy persistence model for courses and completed reviews."""

from __future__ import annotations

import enum

from sqlalchemy import JSON, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):  # noqa: UP042 -- Python 3.10 compatibility
    METHODIST = "methodist"
    STUDENT = "student"
    REVIEWER = "reviewer"


class SubmissionStatus(str, enum.Enum):  # noqa: UP042 -- Python 3.10 compatibility
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Authentication is deliberately simple for this local demo service. Do not
    # use this field for production credentials without replacing it with a
    # password hash and a proper authentication provider.
    password: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    first_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    telegram: Mapped[str] = mapped_column(String(256), nullable=False, default="")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False, default=2026)
    cohort: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    stream: Mapped[int] = mapped_column(nullable=False, default=1)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    cover_color: Mapped[str] = mapped_column(String(16), nullable=False, default="#3B6EF5")
    students_count: Mapped[int] = mapped_column(nullable=False, default=0)
    description: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    capacity: Mapped[int] = mapped_column(nullable=False, default=30)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    rubric_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class CourseReviewer(Base):
    __tablename__ = "course_reviewers"
    __table_args__ = (UniqueConstraint("course_id", "reviewer_id", name="uq_course_reviewer"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_course_student"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class HomeworkProgress(Base):
    __tablename__ = "homework_progress"
    __table_args__ = (UniqueConstraint("task_id", "student_id", name="uq_task_student_progress"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    submitted: Mapped[bool] = mapped_column(nullable=False, default=False)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus), nullable=False, default=SubmissionStatus.PENDING
    )


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), nullable=False, unique=True)
    review_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    pdf_path: Mapped[str] = mapped_column(String(1024), nullable=False)
