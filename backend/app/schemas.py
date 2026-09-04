from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    year: int
    cohort: str
    assignments_count: int = 0


class AssignmentListOut(BaseModel):
    id: int
    title: str
    deadline: datetime
    total: int
    reviewed: int


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


class Criterion(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    max_score: int = Field(ge=0, le=100)


class AssignmentOut(BaseModel):
    id: int
    course_id: int
    title: str
    deadline: datetime
    task_url: str
    criteria: list[Criterion]
    reviewer_guide: str
    submissions: list[SubmissionOut]


class ReviewUpdate(BaseModel):
    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=3, max_length=3000)
    integrity_flag: str | None = Field(default=None, max_length=1000)


class CriteriaUpdate(BaseModel):
    criteria: list[Criterion] = Field(min_length=1)
    reviewer_guide: str = Field(min_length=3, max_length=5000)


class ClarificationCreate(BaseModel):
    message: str = Field(min_length=5, max_length=2000)


class ClarificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    assignment_id: int
    author: str
    message: str
    status: str
    created_at: datetime
