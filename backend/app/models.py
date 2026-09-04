from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    telegram: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    tokens: Mapped[list["AuthToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    user: Mapped[User] = relationship(back_populates="tokens")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    year: Mapped[int] = mapped_column(Integer)
    cohort: Mapped[str] = mapped_column(String(80))
    stream: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    cover_color: Mapped[str] = mapped_column(String(40), default="#2563EB")
    students_count: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    capacity: Mapped[int] = mapped_column(Integer, default=30)
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    reviewer_links: Mapped[list["CourseReviewer"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    enrollment_applications: Mapped[list["EnrollmentApplication"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class CourseReviewer(Base):
    __tablename__ = "course_reviewers"
    __table_args__ = (UniqueConstraint("course_id", "user_id", name="uq_course_reviewers_course_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course: Mapped[Course] = relationship(back_populates="reviewer_links")
    user: Mapped[User] = relationship()


class EnrollmentApplication(Base):
    __tablename__ = "enrollment_applications"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_enrollment_course_student"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    course: Mapped[Course] = relationship(back_populates="enrollment_applications")
    student: Mapped[User] = relationship(foreign_keys=[user_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_user_id])


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    title: Mapped[str] = mapped_column(String(200))
    number: Mapped[int] = mapped_column(Integer, default=1)
    deadline: Mapped[datetime] = mapped_column(DateTime)
    task_url: Mapped[str] = mapped_column(String(500))
    criteria_url: Mapped[str] = mapped_column(String(500), default="")
    criteria: Mapped[list[dict]] = mapped_column(JSON)
    reviewer_guide: Mapped[str] = mapped_column(Text)
    course: Mapped[Course] = relationship(back_populates="assignments")
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )
    reviewers: Mapped[list["AssignmentReviewer"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class AssignmentReviewer(Base):
    __tablename__ = "assignment_reviewers"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    telegram: Mapped[str] = mapped_column(String(120))
    checked: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    assignment: Mapped[Assignment] = relationship(back_populates="reviewers")
    user: Mapped[User | None] = relationship()


class Submission(Base):
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "student_user_id",
            name="uq_submission_assignment_student",
        ),
    )

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    student_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    student_name: Mapped[str] = mapped_column(String(120))
    work_url: Mapped[str] = mapped_column(String(500))
    stepik_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    integrity_flag: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    criterion_scores: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    student: Mapped[User | None] = relationship(foreign_keys=[student_user_id])
    reviewer_user: Mapped[User | None] = relationship(foreign_keys=[reviewer_user_id])


class ClarificationRequest(Base):
    __tablename__ = "clarification_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    author: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
