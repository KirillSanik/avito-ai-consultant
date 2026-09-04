import re
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from common.models import EvaluationReport, TaskRubric


def _register_font() -> str:
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if font_path.is_file():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(font_path)))
        return "DejaVuSans"
    return "Helvetica"


def generate_evaluation_pdf(eval_json_path: str, output_pdf_path: str) -> str:
    evaluation_path = Path(eval_json_path)
    report = EvaluationReport.model_validate_json(evaluation_path.read_text(encoding="utf-8"))
    task_path = evaluation_path.parents[1] / "tasks" / f"{report.task_id}.json"
    rubric = TaskRubric.model_validate_json(task_path.read_text(encoding="utf-8")) if task_path.is_file() else None
    output_path = Path(output_pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = _register_font()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontName=font_name, alignment=TA_CENTER, fontSize=16, leading=20
    )
    heading_style = ParagraphStyle(
        "Heading", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=16, spaceBefore=8
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName=font_name, fontSize=9, leading=12, alignment=TA_JUSTIFY
    )
    label_style = ParagraphStyle("Label", parent=body_style, fontName=font_name, fontSize=10, leading=13)
    small_style = ParagraphStyle("Small", parent=body_style, fontSize=9, leading=12)
    criterion_style = ParagraphStyle("Criterion", parent=body_style, fontSize=14.4, leading=18, spaceBefore=6)
    breakdown_style = ParagraphStyle("Breakdown", parent=body_style, fontSize=9, leading=12)
    summary_style = ParagraphStyle("Summary", parent=body_style, fontSize=10, leading=14)
    task_title = html_escape(rubric.title if rubric else report.task_id)
    moscow_time = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
    story = [
        Paragraph("Отчёт о проверке", title_style),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Задание:</b> {task_title}", body_style),
        Paragraph(f"<b>Время проверки:</b> {moscow_time} (Москва)", body_style),
        Paragraph(f"<b>Итоговый балл:</b> {report.total_score:g} / {report.max_total_score:g}", body_style),
        Spacer(1, 4 * mm),
        Paragraph("Сводная таблица баллов", heading_style),
    ]
    score_rows = [
        [
            Paragraph("<b>Критерий</b>", label_style),
            Paragraph("<b>Получено</b>", label_style),
            Paragraph("<b>Максимум</b>", label_style),
        ]
    ]
    for index, result in enumerate(report.criterion_results):
        score_rows.append(
            [
                Paragraph(f'<link href="#criterion-{index}">{html_escape(result.criterion_name)}</link>', small_style),
                str(result.assigned_score),
                str(result.max_points),
            ]
        )
    story.append(Table(score_rows, colWidths=[136 * mm, 22 * mm, 22 * mm], repeatRows=1, style=TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e2f3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])))
    story.extend([
        Paragraph("Краткая сводка", heading_style),
        Table(
            [[Paragraph(_linkify(report.summary_feedback), summary_style)]],
            colWidths=[180 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff2cc")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#bf9000")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]),
        ),
        Paragraph("Отчёт об использовании ИИ", heading_style),
        Table(
            [[Paragraph("Раздел будет заполнен после подключения соответствующих сервисов.", body_style)]],
            colWidths=[180 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f2f2")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]),
        ),
        Paragraph("Разбор по критериям", heading_style),
        HRFlowable(width="100%", thickness=0.5, color=colors.grey),
    ])
    for index, result in enumerate(report.criterion_results):
        criterion = rubric.criteria[index] if rubric and index < len(rubric.criteria) else None
        description = criterion.description if criterion else ""
        evidence = "<br/>".join(f"• {_linkify(item)}" for item in result.evidence) or (
            "Доказательства не представлены."
        )
        story.extend([
            Paragraph(
                f'<a name="criterion-{index}"/><b>{html_escape(result.criterion_name)}</b> — '
                f"{result.assigned_score:g}/{result.max_points:g}",
                criterion_style,
            ),
            Paragraph(_linkify(description), breakdown_style),
            Paragraph(
                f'<font size="11"><b>Обоснование:</b></font><br/>{_linkify(result.reasoning)}',
                breakdown_style,
            ),
            Paragraph(
                f'<font size="11"><b>Доказательства:</b></font><br/>{evidence}',
                breakdown_style,
            ),
            Spacer(1, 3 * mm),
        ])
    SimpleDocTemplate(
        str(output_path), pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm
    ).build(story)
    return str(output_path)


def _linkify(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"https?://[^\s<>\"']+", text):
        parts.append(html_escape(text[cursor:match.start()]))
        url = match.group(0).rstrip(".,;:!?)]}")
        href = html_escape(url, quote=True)
        parts.append(f'<link href="{href}" color="blue">{html_escape(url)}</link>')
        parts.append(html_escape(text[match.start() + len(url):match.end()]))
        cursor = match.end()
    parts.append(html_escape(text[cursor:]))
    return "".join(parts)
