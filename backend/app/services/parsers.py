import logging
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import docx
import httpx
import openpyxl
import pdfplumber
from bs4 import BeautifulSoup

from .contracts import Constraints, Criterion, TaskRubric


SUPPORTED_TASK_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".md", ".txt"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
URL_TIMEOUT_SECONDS = 20.0

logger = logging.getLogger(__name__)


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
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass
        data = source.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, bytes):
        raise ValueError("File stream did not return binary content")
    if not data:
        raise ValueError("File is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File exceeds the 20 MB upload limit")
    if extension == ".pdf":
        pages = _extract_pdf_text(data)
        return _parsed_document("\n\n".join(pages), {"format": "pdf", "pages": len(pages)})
    if extension == ".docx":
        document = docx.Document(BytesIO(data))
        text = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            text.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
        return _parsed_document("\n".join(text), {"format": "docx", "paragraphs": len(document.paragraphs), "tables": len(document.tables)})
    if extension == ".xlsx":
        workbook = openpyxl.load_workbook(BytesIO(data), data_only=False, read_only=True)
        rows: list[str] = []
        row_count = 0
        for sheet in workbook.worksheets:
            rows.append(f"# {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                rows.append(" | ".join(str(value or "") for value in row))
                row_count += 1
        return _parsed_document("\n".join(rows), {"format": "xlsx", "sheets": workbook.sheetnames, "rows": row_count})
    return _parsed_document(data.decode("utf-8", errors="replace"), {"format": extension.lstrip(".")})


def _extract_pdf_text(data: bytes) -> list[str]:
    buffer = BytesIO(data)
    try:
        with pdfplumber.open(buffer) as pdf:
            pages: list[str] = []
            for page in pdf.pages:
                layout_text = page.extract_text(layout=True) or ""
                page_text = layout_text if layout_text.strip() else (page.extract_text() or "")
                pages.append(page_text.strip())
            return pages
    finally:
        buffer.close()


def extract_task_text(path: str | Path) -> str:
    return parse_document(path).text


def extract_url_text(url: str) -> str:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("URL must use http or https")
    if parsed_url.netloc.lower() in {"github.com", "www.github.com"}:
        parts = [part for part in parsed_url.path.split("/") if part]
        if len(parts) >= 4 and parts[2] in {"blob", "raw"}:
            raw_url = f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{'/'.join(parts[3:])}"
            return _extract_http_text(raw_url)
        if len(parts) >= 2:
            owner, repo = parts[:2]
            for filename in ("README.md", "readme.md"):
                for branch in ("main", "master"):
                    try:
                        return _extract_http_text(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filename}")
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
    return _extract_http_text(url)


def _extract_http_text(url: str) -> str:
    with httpx.Client(timeout=URL_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    path = urlparse(str(response.url)).path.lower()
    archive_type = _office_archive_type(response.content)
    if "pdf" in content_type or path.endswith(".pdf") or response.content.startswith(b"%PDF-"):
        text = parse_document(response.content, "task.pdf").text
    elif "wordprocessingml" in content_type or path.endswith(".docx") or archive_type == "docx":
        text = parse_document(response.content, "task.docx").text
    elif "spreadsheetml" in content_type or path.endswith(".xlsx") or archive_type == "xlsx":
        text = parse_document(response.content, "task.xlsx").text
    elif path.endswith((".txt", ".md")) or "text/plain" in content_type or "text/markdown" in content_type:
        text = _clean_text(response.content.decode("utf-8", errors="replace"))
    else:
        text = _html_to_text(response.text)
    logger.info("task.url_extracted url=%s chars=%s preview=%r", url, len(text), text[:200])
    return text


def _office_archive_type(data: bytes) -> str | None:
    if not data.startswith(b"PK\x03\x04"):
        return None
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return None


def _html_to_text(html: str) -> str:
    document = BeautifulSoup(html, "html.parser")
    for element in document(["script", "style", "noscript"]):
        element.decompose()
    return _clean_text(document.get_text("\n"))


def _parsed_document(text: str, metadata: dict[str, object]) -> ParsedDocument:
    cleaned = _clean_text(text)
    logger.info("task.document_extracted format=%s chars=%s preview=%r", metadata.get("format"), len(cleaned), cleaned[:200])
    return ParsedDocument(cleaned, metadata)


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


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
    if not parsed:
        parsed = _infer_criteria(text)
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


def _infer_criteria(text: str) -> list[Criterion]:
    scope = _first_paragraph(text) or "задания"
    return [
        Criterion(name="Соответствие требованиям задания", description=f"Насколько результат соответствует целям и обязательным требованиям {scope}.", max_points=4.0),
        Criterion(name="Корректность и качество решения", description="Корректность результата, обоснованность решений и обработка значимых случаев.", max_points=4.0),
        Criterion(name="Полнота и оформление результата", description="Полнота материалов, понятность изложения и качество представления итоговой работы.", max_points=2.0),
    ]


def _extract_guidelines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.match(r"^\s*\d+[.)]", line)]


def _first_paragraph(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")
