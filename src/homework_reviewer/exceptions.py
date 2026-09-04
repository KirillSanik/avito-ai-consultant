"""Иерархия доменных исключений модуля homework_reviewer.

Наружу из движка оценки пробрасывается только эта иерархия; CLI-фасад
(``homework_reviewer.cli``) сам оборачивает их в ``click.ClickException``.
"""


class HomeworkReviewError(Exception):
    """Базовое исключение модуля ревью домашних заданий."""


class EvaluationError(HomeworkReviewError):
    """Сбой оценки работы (LLM-провайдер после исчерпания повторов/цепочки моделей)."""
