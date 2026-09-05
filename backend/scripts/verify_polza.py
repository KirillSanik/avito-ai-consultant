"""Проверка методов ревью и детекции AI против POLZA API (cloud-провайдер).

Вызывает реальные сервисные методы (LLMService) с облачной конфигурацией из .env
и валидирует, что ответы распаршиваются как JSON и проходят pydantic-валидацию:
  1) parse_rubric      — подготовка критериев для ревью (TaskRubric)
  2) grade_criterion   — ревью по критерию (CriterionResult)
  3) assess_ai_origin  — детекция AI (AIAssessmentResult)
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Подгружаем .env из корня репозитория, если переменные не заданы
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
if ENV_FILE.is_file():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
else:
    sys.exit("FAIL: .env not found")

from app.services.contracts import (  # noqa: E402
    Criterion,
    SubmissionData,
    TaskRubric,
)
from app.services.llm import LLMService  # noqa: E402
from app.services.settings import PipelineSettings  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


async def main() -> None:
    settings = PipelineSettings.from_environment()
    print(f"provider={settings.llm_provider} model={settings.model_name} "
          f"base_url={settings.polza_base_url} key={'set' if settings.polza_api_key else 'MISSING'}")
    if settings.llm_provider in ("local", "ollama"):
        sys.exit("FAIL: LLM_PROVIDER должен быть cloud для проверки POLZA API")
    if not settings.polza_api_key:
        sys.exit("FAIL: POLZA_API_KEY отсутствует")

    llm = LLMService(settings)

    # --- 1. parse_rubric (подготовка ревью) ---
    t0 = time.monotonic()
    fallback = TaskRubric(
        task_id="task-1",
        title="Исследование продуктовой метрики",
        description="Проверить воспроизводимость расчётов.",
        full_instructions="Проанализируйте метрику retention на данных из файла data.csv.",
        criteria=[Criterion(name="Корректность анализа", description="Точность расчётов", max_points=40)],
        total_points=40,
    )
    try:
        rubric = await llm.parse_rubric("task-1", fallback.title, "Проанализируйте метрику retention на данных из файла data.csv.", fallback)
        check("parse_rubric: TaskRubric валиден",
              rubric.task_id == "task-1" and isinstance(rubric.criteria, list),
              f"criteria={len(rubric.criteria)}, total={rubric.total_points}, {time.monotonic()-t0:.1f}s")
        print("    title:", rubric.title[:100])
    except Exception as exc:
        check("parse_rubric", False, f"{type(exc).__name__}: {exc}")
        rubric = None

    # --- 2. grade_criterion (ревью) ---
    t0 = time.monotonic()
    try:
        criterion = Criterion(name="Корректность анализа", description="Точность расчётов", max_points=40)
        submission = SubmissionData(
            submission_id="sub-1",
            task_id="task-1",
            file_type="markdown",
            file_tree=["README.md", "analysis.py"],
            raw_text="Расчёт retention: 45% на 30 дней. Использована формула unique users на конец периода / unique users на начало. Данные из data.csv.",
        )
        result = await llm.grade_criterion(criterion, rubric or fallback, submission)
        valid = (
            0 <= result.assigned_score <= criterion.max_points
            and result.criterion_name == criterion.name
            and bool(result.reasoning)
        )
        check("grade_criterion: CriterionResult валиден", valid,
              f"score={result.assigned_score}/{result.max_points}, {time.monotonic()-t0:.1f}s")
        print("    reasoning:", result.reasoning[:120].replace("\n", " "))
    except Exception as exc:
        check("grade_criterion", False, f"{type(exc).__name__}: {exc}")

    # --- 3. assess_ai_origin (детекция AI) ---
    t0 = time.monotonic()
    try:
        assessment = await llm.assess_ai_origin(
            "Проанализируйте метрику retention на данных из файла data.csv.",
            ["README.md", "analysis.py"],
            [
                {"hash": "a1b2c3", "author": "student", "date": "2026-09-01T10:00:00+03:00", "message": "initial commit"},
                {"hash": "d4e5f6", "author": "student", "date": "2026-09-03T12:00:00+03:00", "message": "fix typo in README"},
            ],
            "import pandas as pd\ndf = pd.read_csv('data.csv')\nretention = df['end'].unique() / df['start'].unique()\nprint(retention)",
        )
        valid = (
            isinstance(assessment.ai_indicators, list)
            and isinstance(assessment.human_indicators, list)
            and bool(assessment.reasoning)
            and 0 <= assessment.confidence <= 1
            and bool(assessment.status)
        )
        check("assess_ai_origin: AIAssessmentResult валиден", valid,
              f"status={assessment.status}, confidence={assessment.confidence}, {time.monotonic()-t0:.1f}s")
        print("    ai_indicators:", json.dumps(assessment.ai_indicators, ensure_ascii=False)[:200])
        print("    reasoning:", assessment.reasoning[:120].replace("\n", " "))
    except Exception as exc:
        check("assess_ai_origin", False, f"{type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)}): {failures}")
        sys.exit(1)
    print("RESULT: PASS — все три метода работают с POLZA API и отдают валидные ответы")


asyncio.run(main())
