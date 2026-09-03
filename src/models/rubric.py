from typing import List

from pydantic import BaseModel, Field, model_validator


class Criterion(BaseModel):
    name: str = Field(description="Название критерия оценивания из русскоязычного задания.")
    description: str = Field(description="Подробное русскоязычное описание того, что проверяется по критерию.")
    min_points: float = Field(default=0, ge=0, description="Минимальное количество баллов за критерий.")
    max_points: float = Field(ge=0, description="Максимальное количество баллов за критерий согласно заданию.")


class Constraints(BaseModel):
    technical_requirements: List[str] = Field(default_factory=list, description="Технические требования к работе, инструментам, файлам или среде выполнения.")
    formatting_requirements: List[str] = Field(default_factory=list, description="Требования к оформлению, структуре, формату и составу сдаваемой работы.")
    submission_requirements: List[str] = Field(default_factory=list, description="Условия и способ сдачи работы, включая сроки, если они указаны.")
    prohibited_actions: List[str] = Field(default_factory=list, description="Запрещённые действия, материалы или способы выполнения работы.")
    additional_requirements: List[str] = Field(default_factory=list, description="Прочие важные ограничения и требования из русскоязычных методических указаний.")

    @model_validator(mode="before")
    @classmethod
    def normalize_list(cls, value):
        if isinstance(value, list):
            return {"additional_requirements": [str(item) for item in value]}
        return value


class TaskRubric(BaseModel):
    task_id: str = Field(description="Уникальный идентификатор задания, переданный при загрузке.")
    title: str = Field(description="Название задания на русском языке.")
    description: str = Field(description="Краткое, но полное описание цели и ожидаемого результата задания на русском языке.")
    full_instructions: str = Field(default="", description="Полный исходный текст задания, извлечённый из загруженного документа.")
    guidelines: List[str] = Field(default_factory=list, description="Пошаговые указания по выполнению задания, извлечённые из русскоязычного исходного документа.")
    criteria: List[Criterion] = Field(default_factory=list, description="Критерии оценивания с названиями, описаниями и диапазонами баллов.")
    constraints: Constraints = Field(default_factory=Constraints, description="Технические, форматные и иные ограничения задания.")
    total_points: float = Field(default=0, ge=0, description="Максимальное суммарное число баллов за задание.")
