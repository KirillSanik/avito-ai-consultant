"""Исключения вынесенного из фич слоя разбора файлов с условием задачи."""


class TaskParseError(Exception):
    """Базовое исключение разбора файла с условием (PDF/DOCX/XLSX → текст → рубрика)."""


class TaskFileError(TaskParseError):
    """Файл не найден или его формат не поддерживается."""


class TaskStructureError(TaskParseError):
    """Не удалось построить рубрику даже с regex-fallback (фатально)."""
