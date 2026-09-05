"""Регрессионные тесты генератора PDF-отчётов.

Ключевой сценарий: ``summary_feedback`` может быть заметно длиннее высоты
страницы. Итоговая сводка должна рендериться как ``Paragraph`` (а не как
одноячеечная ``Table``), который корректно разбивается между страницами;
в противном случае reportlab бросает ``LayoutError``.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest

from common.models import AIAssessmentResult, Criterion, CriterionResult, EvaluationReport, TaskRubric
from homework_reviewer.reports.pdf_generator import generate_review_pdf


def _report_with_long_feedback() -> EvaluationReport:
    return EvaluationReport(
        task_id="t1",
        submission_id="s-long-feedback",
        total_score=6.5,
        max_total_score=10,
        criterion_results=[
            CriterionResult(
                criterion_id="c-1",
                criterion_name="Correctness",
                assigned_score=6.5,
                max_points=10,
                reasoning="Reasoning text.",
                evidence=["main.py"],
            )
        ],
        summary_feedback="Итог: 6.5 из 10 баллов. Корректность описания продукта и цен. " * 800,
    )


def _rubric(task_id: str) -> TaskRubric:
    return TaskRubric(
        task_id=task_id,
        title="Long feedback task",
        description="desc",
        full_instructions="instructions",
        criteria=[Criterion(name="Correctness", description="c-desc", max_points=10)],
        total_points=10,
    )


def test_generate_review_pdf_with_long_summary_feedback(tmp_path: Path) -> None:
    report = _report_with_long_feedback()
    rubric = _rubric(report.task_id)
    output = tmp_path / "reports" / "long.pdf"

    rendered = generate_review_pdf(report, rubric, str(output))

    assert rendered == str(output)
    assert output.is_file()
    assert output.stat().st_size > 0
    assert output.read_bytes().startswith(b"%PDF")


def _report(task_id: str, submission_id: str) -> EvaluationReport:
    return EvaluationReport(
        task_id=task_id,
        submission_id=submission_id,
        total_score=7.0,
        max_total_score=10,
        criterion_results=[
            CriterionResult(
                criterion_id="c-1",
                criterion_name="Correctness",
                assigned_score=7.0,
                max_points=10,
                reasoning="Reasoning.",
                evidence=["main.py"],
            )
        ],
        summary_feedback="Итог: 7 из 10 баллов.",
    )


def _rubric_simple(task_id: str) -> TaskRubric:
    return TaskRubric(
        task_id=task_id,
        title="AI task",
        description="desc",
        full_instructions="instructions",
        criteria=[Criterion(name="Correctness", description="c-desc", max_points=10)],
        total_points=10,
    )


def test_review_pdf_renders_ai_assessment_text(tmp_path: Path) -> None:
    report = _report("t-ai", "s-ai")
    rubric = _rubric_simple(report.task_id)
    ai = AIAssessmentResult(
        status="yellow",
        confidence=0.73,
        reasoning="Есть признаки как ИИ, так и самостоятельной работы; итог смешанный.",
        ai_indicators=["Неестественно ровная структура кода", "Повторяющиеся комментарии"],
        human_indicators=["Нестандартные имена переменных", "Опечатки в комментариях"],
    )
    output = tmp_path / "reports" / "ai.pdf"

    generate_review_pdf(report, rubric, str(output), ai)

    assert output.is_file()
    with pdfplumber.open(str(output)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Вердикт" in text
    assert "YELLOW" in text
    assert "уверенность 0.73" in text
    assert "Обоснование:" in text
    assert "Признаки ИИ-генерации:" in text
    assert "Неестественно ровная структура кода" in text
    assert "Признаки самостоятельной работы:" in text
    assert "Нестандартные имена переменных" in text


def test_review_pdf_without_ai_assessment_renders(tmp_path: Path) -> None:
    report = _report("t-noai", "s-noai")
    rubric = _rubric_simple(report.task_id)
    output = tmp_path / "reports" / "no-ai.pdf"

    generate_review_pdf(report, rubric, str(output))

    assert output.is_file()
    with pdfplumber.open(str(output)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Информация о детекции ИИ недоступна." in text