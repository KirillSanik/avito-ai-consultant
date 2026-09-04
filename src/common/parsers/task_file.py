"""Этап (а) разбора условия: извлечение текста из PDF/DOCX/XLSX без LLM.

Вынесен в общий слой, чтобы ``Pipeline`` выполнял парсинг файла строго один
раз на запрос до ``asyncio.gather`` (ТЗ §5.1). Синхронный метод — в async-
контексте вызывать через ``asyncio.to_thread``.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from common.parsers.docx_parser import DOCXParser
from common.parsers.exceptions import TaskFileError
from common.parsers.xlsx_parser import XLSXParser

#: Поддерживаемые расширения файлов с условием (ТЗ §4.1).
SUPPORTED_TASK_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".xlsx"})


def _extract_pdf_text(pdf_path: Path) -> str:
    """Текст PDF постранично + таблицы в markdown (перенесено из ``TaskParser.extract_pdf_content``)."""
    sections: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_parts = [f"## Страница {page_number}"]
            text = page.extract_text()
            if text:
                page_parts.append(text)
            for table_number, table in enumerate(page.extract_tables(), start=1):
                markdown = _table_to_markdown(table)
                if markdown:
                    page_parts.append(f"### Таблица {table_number}\n{markdown}")
            sections.append("\n\n".join(page_parts))
    return "\n\n".join(sections)


def _table_to_markdown(table: list[list[str | None]]) -> str:
    rows = [[(cell or "").replace("|", "\\|").replace("\n", " ").strip() for cell in row] for row in table if row]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    separator = ["-" * 3] * width
    body = normalized_rows[1:]
    return "\n".join([_row_to_markdown(header), _row_to_markdown(separator), *[_row_to_markdown(row) for row in body]])


def _row_to_markdown(row: list[str]) -> str:
    return "| " + " | ".join(row) + " |"


def extract_task_text(path: str | Path) -> str:
    """Полный текст условия из файла (PDF/DOCX/XLSX); LLM не используется.

    :raises TaskFileError: файл не найден либо расширение не поддерживается.
    """
    source = Path(path)
    if not source.is_file():
        raise TaskFileError(f"Файл с условием не найден: {path}")
    extension = source.suffix.lower()
    if extension == ".pdf":
        return _extract_pdf_text(source)
    if extension == ".docx":
        return DOCXParser().parse(str(source))["raw_text"]
    if extension == ".xlsx":
        return XLSXParser().parse(str(source))["raw_text"]
    raise TaskFileError(
        f"Неподдерживаемый формат файла с условием: {extension or '(без расширения)'}; "
        f"поддерживаются: {', '.join(sorted(SUPPORTED_TASK_EXTENSIONS))}"
    )
