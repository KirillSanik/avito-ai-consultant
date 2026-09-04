from pydantic import BaseModel, Field, model_validator


class CriterionResult(BaseModel):
    criterion_id: str = Field(description="Идентификатор оценённого критерия.")
    criterion_name: str = Field(description="Название оценённого критерия.")
    assigned_score: float = Field(ge=0, description="Количество баллов, назначенное за критерий.")
    max_points: float = Field(ge=0, description="Максимальное количество баллов за критерий.")
    reasoning: str = Field(description="Обоснование выставленной оценки.")
    evidence: list[str] = Field(default_factory=list, description="Фрагменты и факты из работы, подтверждающие оценку.")

    @model_validator(mode="after")
    def validate_score_range(self) -> "CriterionResult":
        if self.assigned_score > self.max_points:
            raise ValueError("assigned_score не может превышать max_points")
        return self


class EvaluationReport(BaseModel):
    task_id: str = Field(description="Идентификатор задания.")
    submission_id: str = Field(description="Идентификатор проверенной работы.")
    total_score: float = Field(ge=0, description="Сумма баллов по всем критериям.")
    max_total_score: float = Field(ge=0, description="Сумма максимальных баллов по всем критериям.")
    criterion_results: list[CriterionResult] = Field(default_factory=list, description="Результаты последовательной проверки по критериям.")
    summary_feedback: str = Field(description="Итоговая обратная связь по работе.")
