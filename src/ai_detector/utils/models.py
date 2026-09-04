"""Pydantic-модели данных модуля ai_detector (data-model.md §1, §4).

Строгая типизация, `Any` отсутствует. Поле `task_compliance_score`
в схеме **не существует** (FR-009): при его получении от LLM схема
отбросит его (`extra="ignore"`), а промпт его не предлагает.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
        min_length=1,
        description="Подробное, аргументированное обоснование вердикта на русском языке. "
                    "Сначала взвесь аргументы за и против, затем сделай вывод.",
    )
    
    status: Literal["green", "yellow", "red"] = Field(
        description="Итоговый вердикт на основе reasoning: 'green' (человек), 'yellow' (смешанный/подозрительный), 'red' (явный ИИ/копипаст)"
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
