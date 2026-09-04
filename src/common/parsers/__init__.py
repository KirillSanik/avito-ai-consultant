"""Вынесенный из фич слой разбора файлов с условием и сдачи (ТЗ §5.1, шаг 1).

Этапы разбора условия:
- (а) ``extract_task_text`` — извлечение текста PDF/DOCX/XLSX без LLM;
- (б) ``parse_task_rubric`` — LLM-структурирование текста в ``TaskRubric``
  (async, ретраи и fallback по цепочке моделей через ``common.llm``).
"""

from common.parsers.docx_parser import DOCXParser
from common.parsers.exceptions import TaskFileError, TaskParseError, TaskStructureError
from common.parsers.task_file import SUPPORTED_TASK_EXTENSIONS, extract_task_text
from common.parsers.task_rubric import (
    clean_and_truncate,
    extract_criteria,
    extract_guidelines,
    fallback_description,
    fallback_title,
    parse_task_rubric,
)
from common.parsers.xlsx_parser import XLSXParser

__all__ = [
    "SUPPORTED_TASK_EXTENSIONS",
    "DOCXParser",
    "TaskFileError",
    "TaskParseError",
    "TaskStructureError",
    "XLSXParser",
    "clean_and_truncate",
    "extract_criteria",
    "extract_guidelines",
    "extract_task_text",
    "fallback_description",
    "fallback_title",
    "parse_task_rubric",
]
