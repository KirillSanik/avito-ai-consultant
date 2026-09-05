from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .contracts import AIAssessmentResult, EvaluationReport, TaskRubric


def generate_review_pdf(report: EvaluationReport, rubric: TaskRubric, ai_assessment: AIAssessmentResult, output_path: str | Path) -> str:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Отчёт о проверке", styles["Title"]),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Задание:</b> {escape(rubric.title)}", styles["BodyText"]),
        Paragraph(f"<b>Итог:</b> {report.total_score:g} / {report.max_total_score:g}", styles["BodyText"]),
        Paragraph(f"<b>AI-вердикт:</b> {escape(ai_assessment.status)} ({ai_assessment.confidence:.2f})", styles["BodyText"]),
        Spacer(1, 5 * mm),
    ]
    rows = [["Критерий", "Балл", "Обоснование"]]
    for result in report.criterion_results:
        rows.append([result.criterion_name, f"{result.assigned_score:g}/{result.max_points:g}", result.reasoning])
    story.append(Table(rows, colWidths=[55 * mm, 25 * mm, 95 * mm], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e2f3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])))
    story.extend([Spacer(1, 5 * mm), Paragraph("Итоговая обратная связь", styles["Heading2"]), Paragraph(escape(report.summary_feedback), styles["BodyText"]), Paragraph("Признаки использования ИИ", styles["Heading2"]), Paragraph(escape(ai_assessment.reasoning), styles["BodyText"])])
    SimpleDocTemplate(str(destination), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    return str(destination)
