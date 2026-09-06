from io import BytesIO

import docx
import openpyxl
from reportlab.pdfgen import canvas

from app.services.parsers import parse_document


def test_parse_pdf_bytes_returns_text_and_metadata() -> None:
    buffer = BytesIO()
    document = canvas.Canvas(buffer)
    document.drawString(72, 720, "PDF assignment text")
    document.save()

    parsed = parse_document(buffer.getvalue(), "assignment.pdf")

    assert "PDF assignment text" in parsed.text
    assert parsed.metadata == {"format": "pdf", "pages": 1}


def test_parse_docx_bytes_returns_text_and_tables() -> None:
    buffer = BytesIO()
    document = docx.Document()
    document.add_paragraph("DOCX assignment text")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Criterion"
    table.cell(0, 1).text = "10"
    document.save(buffer)

    parsed = parse_document(buffer.getvalue(), "assignment.docx")

    assert "DOCX assignment text" in parsed.text
    assert "Criterion | 10" in parsed.text
    assert parsed.metadata["format"] == "docx"


def test_parse_xlsx_bytes_returns_text_and_sheet_metadata() -> None:
    buffer = BytesIO()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Rubric"
    sheet.append(["Criterion", "Points"])
    sheet.append(["Analysis", 10])
    workbook.save(buffer)

    parsed = parse_document(buffer.getvalue(), "assignment.xlsx")

    assert "# Rubric" in parsed.text
    assert "Analysis | 10" in parsed.text
    assert parsed.metadata["sheets"] == ["Rubric"]
