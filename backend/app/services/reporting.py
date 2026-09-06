import logging
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .contracts import AIAssessmentResult, EvaluationReport, TaskRubric

logger = logging.getLogger(__name__)

_FONT_READY = False
_FONT_REGULAR = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

# Кандидаты TTF-шрифтов с поддержкой кириллицы: (regular, bold).
# Встроенные шрифты reportlab (Helvetica и др.) кириллицу не поддерживают —
# без TTF-шрифта русские буквы в PDF выглядят как чёрные квадраты.
_FONT_CANDIDATES: list[tuple[str, str]] = [
    # Debian/Ubuntu: пакет fonts-dejavu-core (ставится в Dockerfile)
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    # Alpine: пакет font-dejavu
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    # Debian/Ubuntu: пакет fonts-liberation
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    # Windows
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
    # macOS
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]


def _ensure_cyrillic_fonts() -> tuple[str, str]:
    """Регистрирует TTF-шрифты с поддержкой кириллицы и возвращает (regular, bold)."""
    global _FONT_READY, _FONT_REGULAR, _FONT_BOLD
    if _FONT_READY:
        return _FONT_REGULAR, _FONT_BOLD
    for regular_path, bold_path in _FONT_CANDIDATES:
        if not Path(regular_path).is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("ReportCyrillic", regular_path))
        except Exception:
            logger.exception("pdf.font.register_failed path=%s", regular_path)
            continue
        _FONT_REGULAR = "ReportCyrillic"
        if Path(bold_path).is_file():
            try:
                pdfmetrics.registerFont(TTFont("ReportCyrillic-Bold", bold_path))
                _FONT_BOLD = "ReportCyrillic-Bold"
            except Exception:
                logger.exception("pdf.font.register_failed path=%s", bold_path)
        registerFontFamily(
            "ReportCyrillic",
            normal=_FONT_REGULAR,
            bold=_FONT_BOLD,
            italic=_FONT_REGULAR,
            boldItalic=_FONT_BOLD,
        )
        logger.info("pdf.font.registered regular=%s bold=%s", regular_path, _FONT_BOLD)
        break
    else:
        logger.warning("pdf.font.no_cyrillic_ttf_found fallback=%s", _FONT_REGULAR)
    _FONT_READY = True
    return _FONT_REGULAR, _FONT_BOLD


def _build_styles() -> dict[str, ParagraphStyle]:
    regular, bold = _ensure_cyrillic_fonts()
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=sample["Title"], fontName=bold),
        "heading": ParagraphStyle("ReportHeading", parent=sample["Heading2"], fontName=bold),
        "body": ParagraphStyle("ReportBody", parent=sample["BodyText"], fontName=regular),
        "table_header": ParagraphStyle("ReportTableHeader", parent=sample["BodyText"], fontName=bold),
    }


def generate_review_pdf(report: EvaluationReport, rubric: TaskRubric, ai_assessment: AIAssessmentResult, output_path: str | Path) -> str:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = _build_styles()
    story = [
        Paragraph("Отчёт о проверке", styles["title"]),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Задание:</b> {escape(rubric.title)}", styles["body"]),
        Paragraph(f"<b>Итог:</b> {report.total_score:g} / {report.max_total_score:g}", styles["body"]),
        Paragraph(f"<b>AI-вердикт:</b> {escape(ai_assessment.status)} ({ai_assessment.confidence:.2f})", styles["body"]),
        Spacer(1, 5 * mm),
    ]
    rows: list[list] = [[
        Paragraph("Критерий", styles["table_header"]),
        Paragraph("Балл", styles["table_header"]),
        Paragraph("Обоснование", styles["table_header"]),
    ]]
    cell_style = styles["body"]
    for result in report.criterion_results:
        rows.append([
            Paragraph(escape(result.criterion_name), cell_style),
            Paragraph(f"{result.assigned_score:g}/{result.max_points:g}", cell_style),
            Paragraph(escape(result.reasoning), cell_style),
        ])
    story.append(Table(rows, colWidths=[55 * mm, 25 * mm, 95 * mm], repeatRows=1, splitInRow=1, style=TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e2f3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])))
    story.extend([
        Spacer(1, 5 * mm),
        Paragraph("Итоговая обратная связь", styles["heading"]),
        Paragraph(escape(report.summary_feedback), styles["body"]),
        Paragraph("Признаки использования ИИ", styles["heading"]),
        Paragraph(escape(ai_assessment.reasoning), styles["body"]),
    ])
    SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    return str(destination)
