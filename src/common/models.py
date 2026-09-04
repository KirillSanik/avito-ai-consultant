"""Единые Pydantic-схемы проекта: единственный источник определений.

Сюда перенесены все схемы обеих фич (``ai_detector`` и ``homework_reviewer``)
плюс новые агрегирующие модели ``TaskCriteria`` и ``ReviewResponse``
(ТЗ «Единый API-сервис проверки домашних заданий» §3.3).

Локальные модули дублирующие определения не содержат — только импорты
из этого модуля (критерий приёмки ТЗ §8).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# ai_detector (data-model §1, §4)
# ---------------------------------------------------------------------------

#: SHA-1 хэш коммита: ровно 40 hex-символов (data-model.md §1).
COMMIT_HASH_PATTERN: str = r"^[0-9a-f]{40}$"


class CommitInfo(BaseModel):
    """Запись не-merge коммита из истории репозитория (FR-003).

    Порядок в истории — по убыванию даты, как отдаёт `git log`.
    """

    model_config = ConfigDict(frozen=True)

    hash: str = Field(
        pattern=COMMIT_HASH_PATTERN,
        description="40 hex-символов (поле %H из git log)",
    )
    author: str = Field(
        min_length=1,
        description="Имя автора коммита (поле %an)",
    )
    date: str = Field(
        description="Дата коммита, ISO 8601 с таймзоной (поле %aI)",
    )
    message: str = Field(
        description="Однострочный subject коммита (поле %s)",
    )

    @field_validator("date")
    @classmethod
    def _validate_date_iso8601(cls, value: str) -> str:
        """Дата обязана парситься `datetime.fromisoformat` и нести таймзону."""
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"date не является строкой ISO 8601: {value!r}") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"date должна содержать таймзону (ISO 8601): {value!r}")
        return value

    @field_validator("message")
    @classmethod
    def _validate_message_single_line(cls, value: str) -> str:
        """Subject (`%s`) однострочен; перенос строки означает битый вывод git (fail-loud)."""
        if "\n" in value or "\r" in value:
            raise ValueError(f"message должен быть однострочным, получен: {value!r}")
        return value


class AIAssessmentResult(BaseModel):
    """Итоговый вердикт «Светофора» по вероятности AI-генерации кода."""

    model_config = ConfigDict(extra="ignore")

    ai_indicators: list[str] = Field(
        description="Список конкретных признаков, указывающих на генерацию ИИ",
    )
    human_indicators: list[str] = Field(
        description="Список признаков, указывающих на человеческую работу",
    )

    reasoning: str = Field(
        min_length=50,
        description="Подробное, аргументированное обоснование вердикта на русском языке. "
                    "Сначала взвесь аргументы за и против, затем сделай вывод.",
    )

    status: Literal["green", "yellow", "red"] = Field(
        description=(
            "Итоговый вердикт на основе reasoning: 'green' (человек), "
            "'yellow' (смешанный/подозрительный), 'red' (явный ИИ/копипаст)"
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Уверенность модели в итоговом вердикте от 0.0 до 1.0",
    )

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        """Допускает любой регистр статуса от модели ('GREEN'/'Green'), приводит к нижнему."""
        if isinstance(value, str):
            return value.lower()
        return value


# ---------------------------------------------------------------------------
# homework_reviewer: рубрика задания
# ---------------------------------------------------------------------------


class Criterion(BaseModel):
    """Критерий оценивания русскоязычного задания."""

    name: str = Field(description="Название критерия оценивания из русскоязычного задания.")
    description: str = Field(description="Подробное русскоязычное описание того, что проверяется по критерию.")
    min_points: float = Field(default=0, ge=0, description="Минимальное количество баллов за критерий.")
    max_points: float = Field(ge=0, description="Максимальное количество баллов за критерий согласно заданию.")


class Constraints(BaseModel):
    """Технические, форматные и иные ограничения задания."""

    technical_requirements: list[str] = Field(
        default_factory=list,
        description="Технические требования к работе, инструментам, файлам или среде выполнения.",
    )
    formatting_requirements: list[str] = Field(
        default_factory=list,
        description="Требования к оформлению, структуре, формату и составу сдаваемой работы.",
    )
    submission_requirements: list[str] = Field(
        default_factory=list,
        description="Условия и способ сдачи работы, включая сроки, если они указаны.",
    )
    prohibited_actions: list[str] = Field(
        default_factory=list,
        description="Запрещённые действия, материалы или способы выполнения работы.",
    )
    additional_requirements: list[str] = Field(
        default_factory=list,
        description="Прочие важные ограничения и требования из русскоязычных методических указаний.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_list(cls, value: object) -> object:
        if isinstance(value, list):
            return {"additional_requirements": [str(item) for item in value]}
        return value


class TaskRubric(BaseModel):
    """Структурированная рубрика задания (результат LLM-разбора условия)."""

    task_id: str = Field(description="Уникальный идентификатор задания, переданный при загрузке.")
    title: str = Field(description="Название задания на русском языке.")
    description: str = Field(
        description="Краткое, но полное описание цели и ожидаемого результата задания на русском языке.",
    )
    full_instructions: str = Field(
        default="", description="Полный исходный текст задания, извлечённый из загруженного документа.",
    )
    guidelines: list[str] = Field(
        default_factory=list,
        description="Пошаговые указания по выполнению задания, извлечённые из русскоязычного исходного документа.",
    )
    criteria: list[Criterion] = Field(
        default_factory=list,
        description="Критерии оценивания с названиями, описаниями и диапазонами баллов.",
    )
    constraints: Constraints = Field(
        default_factory=Constraints, description="Технические, форматные и иные ограничения задания.",
    )
    total_points: float = Field(default=0, ge=0, description="Максимальное суммарное число баллов за задание.")


class ParsedTaskRubric(BaseModel):
    """Промежуточная схема LLM-разбора условия (до дополнения полными инструкциями)."""

    task_id: str
    title: str
    description: str
    guidelines: list[str] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)


# ---------------------------------------------------------------------------
# homework_reviewer: сдача и оценка
# ---------------------------------------------------------------------------


class LinkInfo(BaseModel):
    """Внешняя ссылка, найденная в работе студента."""

    url: str = Field(description="Адрес ссылки, найденной в работе студента.")
    status_code: int = Field(description="Код HTTP-ответа или 0, если запрос не был выполнен.")
    is_accessible: bool = Field(description="Доступен ли ресурс для автоматической проверки.")
    content_summary: str = Field(description="Краткое содержание доступной страницы или описание ошибки.")
    is_google_doc: bool = Field(description="Указывает, относится ли ссылка к сервисам Google Docs.")


class ExcelAudit(BaseModel):
    """Аудит формул Excel-рабочей книги."""

    sheet_names: list[str] = Field(default_factory=list, description="Названия листов рабочей книги.")
    total_rows: int = Field(default=0, ge=0, description="Общее число непустых строк на всех листах.")
    has_formulas: bool = Field(default=False, description="Есть ли в книге формулы.")
    hardcoded_count: int = Field(default=0, ge=0, description="Количество заполненных ячеек с введёнными значениями.")
    formula_count: int = Field(default=0, ge=0, description="Количество ячеек с формулами.")


class SubmissionData(BaseModel):
    """Разобранная сдача студента (файл или клонированный репозиторий)."""

    submission_id: str = Field(description="Идентификатор разбираемой сдачи.")
    task_id: str = Field(description="Идентификатор задания, к которому относится сдача.")
    file_type: str = Field(description="Тип обработанной сдачи: xlsx, docx, pdf или github.")
    file_tree: list[str] = Field(
        default_factory=list, description="Пути файлов, входящие в локальную сдачу или репозиторий."
    )
    raw_text: str = Field(description="Извлечённый текст и табличное представление содержимого файла.")
    tables: list[dict] = Field(default_factory=list, description="Таблицы работы в структурированном виде.")
    excel_audit: ExcelAudit | None = Field(default=None, description="Результат аудита формул Excel, если применимо.")
    resolved_links: list[LinkInfo] = Field(default_factory=list, description="Проверенные внешние ссылки из работы.")
    image_count: int = Field(default=0, ge=0, description="Количество встроенных изображений.")


class CriterionResult(BaseModel):
    """Результат оценки по одному критерию."""

    criterion_id: str = Field(description="Идентификатор оценённого критерия.")
    criterion_name: str = Field(description="Название оценённого критерия.")
    assigned_score: float = Field(ge=0, description="Количество баллов, назначенное за критерий.")
    max_points: float = Field(ge=0, description="Максимальное количество баллов за критерий.")
    reasoning: str = Field(description="Обоснование выставленной оценки.")
    evidence: list[str] = Field(default_factory=list, description="Фрагменты и факты из работы, подтверждающие оценку.")

    @model_validator(mode="after")
    def validate_score_range(self) -> CriterionResult:
        if self.assigned_score > self.max_points:
            raise ValueError("assigned_score не может превышать max_points")
        return self


class EvaluationReport(BaseModel):
    """Итоговый отчёт проверки работы по всем критериям."""

    task_id: str = Field(description="Идентификатор задания.")
    submission_id: str = Field(description="Идентификатор проверенной работы.")
    total_score: float = Field(ge=0, description="Сумма баллов по всем критериям.")
    max_total_score: float = Field(ge=0, description="Сумма максимальных баллов по всем критериям.")
    criterion_results: list[CriterionResult] = Field(
        default_factory=list, description="Результаты последовательной проверки по критериям."
    )
    summary_feedback: str = Field(description="Итоговая обратная связь по работе.")


# ---------------------------------------------------------------------------
# Новые агрегирующие модели единого API (ТЗ §3.3, §5.1)
# ---------------------------------------------------------------------------


class TaskCriteria(BaseModel):
    """Общее представление распарсенного условия задачи.

    Заполняется ``Pipeline`` строго один раз на запрос: ``text`` — исходный
    текст документа (вход для промпта детектора), ``rubric`` — структура
    критериев (вход для ревьюера).
    """

    task_id: str = Field(default="review", description="Идентификатор задания (по умолчанию — имя файла ТЗ).")
    text: str = Field(description="Полный извлечённый текст условия задачи (без LLM).")
    rubric: TaskRubric | None = Field(
        default=None,
        description="Структурированная рубрика (LLM-разбор с regex-fallback), если доступна.",
    )


class ReviewResponse(BaseModel):
    """Ответ ``POST /review``: агрегация результатов детектора и ревьюера."""

    repo_url: str = Field(description="URL репозитория, отправленного на проверку.")
    task_id: str = Field(description="Идентификатор задания (имя файла ТЗ).")
    ai_assessment: AIAssessmentResult = Field(description="Вердикт детекции AI-генерации.")
    evaluation: EvaluationReport = Field(description="Оценка работы по критериям задания.")
