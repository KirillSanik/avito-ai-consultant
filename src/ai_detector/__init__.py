"""ai_detector — детекция AI-генерации кода в репозиториях с решениями домашних заданий.

Публичный экспорт по контракту contracts/public-api.md §1: всё, что не
экспортировано здесь, считается внутренним и может меняться без предупреждения.
"""

from ai_detector.exceptions import (
    AIDetectionError,
    CodeAggregationError,
    LLMJudgementError,
    MetadataExtractionError,
    RepoCloneError,
)
from ai_detector.models import AIAssessmentResult, CommitInfo
from ai_detector.service import AIDetectionService

__all__ = [
    "AIDetectionError",
    "AIDetectionService",
    "AIAssessmentResult",
    "CodeAggregationError",
    "CommitInfo",
    "LLMJudgementError",
    "MetadataExtractionError",
    "RepoCloneError",
]
