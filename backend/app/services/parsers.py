import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import docx
import openpyxl
import pdfplumber

from .contracts import Constraints, Criterion, TaskRubric


SUPPORTED_TASK_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".md"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    metadata: dict[str, object]


def parse_document(
    source: str | Path | bytes | BinaryIO,
    filename: str | None = None,
) -> ParsedDocument:
    path = Path(source) if isinstance(source, (str, Path)) else None
    name = filename or (path.name if path else "")
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED_TASK_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {extension or 'unknown'}")
    if path is not None:
        if not path.is_file():
            raise ValueError("File does not exist")
        data = path.read_bytes()
    elif isinstance(source, bytes):
        data = source
    else:
        data = source.read()
    if not data:
        raise ValueError("File is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File exceeds the 20 MB upload limit")
    if extension == ".pdf":
        with pdfplumber.open(BytesIO(data)) as pdf:
            pages = [(page.extract_text() or "").strip() for page in pdf.pages]
        return ParsedDocument(_clean_text("\n\n".join(pages)), {"format": "pdf", "pages": len(pages)})
    if extension == ".docx":
        document = docx.Document(BytesIO(data))
        text = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            text.extend(" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows)
        return ParsedDocument(_clean_text("\n".join(text)), {"format": "docx", "paragraphs": len(document.paragraphs), "tables": len(document.tables)})
    if extension == ".xlsx":
        workbook = openpyxl.load_workbook(BytesIO(data), data_only=False, read_only=True)
        rows: list[str] = []
        row_count = 0
        for sheet in workbook.worksheets:
            rows.append(f"# {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                rows.append(" | ".join(str(value or "") for value in row))
                row_count += 1
        return ParsedDocument(_clean_text("\n".join(rows)), {"format": "xlsx", "sheets": workbook.sheetnames, "rows": row_count})
    return ParsedDocument(_clean_text(data.decode("utf-8", errors="replace")), {"format": "md"})


def extract_task_text(path: str | Path) -> str:
    return parse_document(path).text


def _clean_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\x00", "").splitlines()).strip()


def fallback_rubric(task_id: str, title: str, text: str, criteria: list[dict] | None = None) -> TaskRubric:
    parsed = [
        Criterion(
            name=str(item.get("title", item.get("name", "Criterion"))),
            description=str(item.get("description", "")),
            max_points=float(item.get("max_score", item.get("max_points", 0))),
        )
        for item in criteria or []
    ]
    if not parsed:
        parsed = _extract_criteria(text)
    return TaskRubric(
        task_id=task_id,
        title=title,
        description=_first_paragraph(text),
        full_instructions=text,
        guidelines=_extract_guidelines(text),
        criteria=parsed,
        constraints=Constraints(),
        total_points=sum(item.max_points for item in parsed),
    )


def _extract_criteria(text: str) -> list[Criterion]:
    result = []
    pattern = re.compile(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s*([^\n]+?)(?:\s*[-—:]\s*)(\d+(?:[.,]\d+)?)\s*(?:балл|point)", re.I)
    for match in pattern.finditer(text):
        result.append(Criterion(name=match.group(1).strip(), max_points=float(match.group(2).replace(",", "."))))
    return result


def _extract_guidelines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.match(r"^\s*\d+[.)]", line)]


def _first_paragraph(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
