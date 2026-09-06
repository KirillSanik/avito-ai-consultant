from pydantic import BaseModel, Field, model_validator


class Criterion(BaseModel):
    name: str
    description: str = ""
    min_points: float = Field(default=0, ge=0)
    max_points: float = Field(ge=0)


class Constraints(BaseModel):
    technical_requirements: list[str] = Field(default_factory=list)
    formatting_requirements: list[str] = Field(default_factory=list)
    submission_requirements: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    additional_requirements: list[str] = Field(default_factory=list)


class TaskRubric(BaseModel):
    task_id: str
    title: str
    description: str = ""
    full_instructions: str = ""
    guidelines: list[str] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    total_points: float = Field(default=0, ge=0)


class LinkInfo(BaseModel):
    url: str
    status_code: int
    is_accessible: bool
    content_summary: str
    is_google_doc: bool = False


class ExcelAudit(BaseModel):
    sheet_names: list[str] = Field(default_factory=list)
    total_rows: int = 0
    has_formulas: bool = False
    hardcoded_count: int = 0
    formula_count: int = 0


class SubmissionData(BaseModel):
    submission_id: str
    task_id: str
    file_type: str
    file_tree: list[str] = Field(default_factory=list)
    raw_text: str = ""
    tables: list[dict] = Field(default_factory=list)
    excel_audit: ExcelAudit | None = None
    resolved_links: list[LinkInfo] = Field(default_factory=list)
    image_count: int = 0


class CriterionResult(BaseModel):
    criterion_id: str
    criterion_name: str
    assigned_score: float = Field(ge=0)
    max_points: float = Field(ge=0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score(self) -> "CriterionResult":
        if self.assigned_score > self.max_points:
            raise ValueError("assigned_score cannot exceed max_points")
        return self


class EvaluationReport(BaseModel):
    task_id: str
    submission_id: str
    total_score: float = Field(ge=0)
    max_total_score: float = Field(ge=0)
    criterion_results: list[CriterionResult] = Field(default_factory=list)
    summary_feedback: str


class AIAssessmentResult(BaseModel):
    ai_indicators: list[str] = Field(default_factory=list)
    human_indicators: list[str] = Field(default_factory=list)
    reasoning: str
    status: str
    confidence: float = Field(ge=0, le=1)


class ReviewResponse(BaseModel):
    repo_url: str
    task_id: str
    ai_assessment: AIAssessmentResult
    evaluation: EvaluationReport
