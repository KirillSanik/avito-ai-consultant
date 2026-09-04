# Automated Homework Reviewer

## 1. Overview

Automated Homework Reviewer is a Python pipeline that extracts a rubric from an assignment, parses a local submission or GitHub repository, and evaluates the submission criterion by criterion with an LLM. Each stage persists validated Pydantic JSON, and an existing evaluation can be rendered as a Russian-language PDF report.

The workflow is designed as an AI draft for human review: the generated score and feedback must be checked by a reviewer before publication.

## 2. Quick Start & Pipeline Verification

Requirements: Python 3.10+ and dependencies from `requirements.txt`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY='your-key'
```

`OPENROUTER_API_KEY` can also be placed in a local `.env` file. Never commit or print it. Use `--provider ollama` with a running Ollama server when an external provider is not required.

Run the complete pipeline with a local submission:

```bash
python main.py ingest-task \
  --file data/Product_Fraud_hw2.pdf \
  --task-id productfraudhw2 \
  --provider openrouter

python main.py parse-submission \
  --file 'data/Product_Fraud_ДЗ2_Решение хорошее.docx' \
  --task-id productfraudhw2

python main.py evaluate \
  --task-id productfraudhw2 \
  --submission-id 'Product_Fraud_ДЗ2_Решение хорошее' \
  --provider openrouter \
  --pdf
```

For a GitHub submission, keep the existing task artifact and run only parsing and evaluation:

```bash
python main.py parse-submission \
  --url https://github.com/ArtemCh101/test_repo \
  --task-id productfraudhw2

python main.py evaluate \
  --task-id productfraudhw2 \
  --submission-id test_repo \
  --provider openrouter \
  --pdf
```

Verify each persisted artifact:

```bash
python - <<'PY'
import json
from pathlib import Path

for path in [
    Path("storage/tasks/productfraudhw2.json"),
    Path("storage/submissions/Product_Fraud_ДЗ2_Решение хорошее.json"),
    Path("storage/evaluations/Product_Fraud_ДЗ2_Решение хорошее.json"),
]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload
    print(path, "OK")
PY
```

The task must be ingested once and then reused by ID. Do not ingest the same assignment again for each submission. Reports are written to `storage/reports/`.

## 3. Stage-by-Stage Breakdown

### Stage 1: Task Ingestion

**Purpose:** Extract assignment text, instructions, constraints, criteria, and maximum scores into a reusable rubric.

**Input:** A task PDF and a unique `--task-id`; optional `--provider`, `--model-name`, and `--test-mode`.

**Output:** `storage/tasks/<task-id>.json`, validated as `TaskRubric`.

**Verification:**

```bash
python main.py ingest-task \
  --file data/Product_BM_ДЗ1_условия.pdf \
  --task-id task1 \
  --provider openrouter

python - <<'PY'
from src.repository.task_repository import TaskRepository

rubric = TaskRepository().load("task1")
assert rubric.criteria
assert rubric.total_points == sum(item.max_points for item in rubric.criteria)
assert all(item.description.strip() and item.max_points >= 0 for item in rubric.criteria)
print("Task ingestion OK:", len(rubric.criteria), "criteria")
PY
```

### Stage 2: Submission Parsing

**Purpose:** Extract text, tables, spreadsheet audit data, repository files, and external links from a submission.

**Input:** Exactly one of `--file` (`.xlsx`, `.docx`, or `.pdf`) or `--url` (an HTTPS GitHub repository), plus an existing task ID.

**Output:** `storage/submissions/<submission-id>.json`, validated as `SubmissionData`. Local file submissions use the file stem as the submission ID; GitHub submissions use the repository name.

**Verification:**

```bash
python main.py parse-submission \
  --file 'data/Product_BM_ДЗ1_Решение хорошее.xlsx' \
  --task-id task1
```

```bash
python - <<'PY'
from src.repository.submission_repository import SubmissionRepository

submission = SubmissionRepository().load("Product_BM_ДЗ1_Решение хорошее")
assert submission.raw_text.strip()
assert submission.task_id == "task1"
assert isinstance(submission.resolved_links, list)
print("Submission parsing OK:", submission.file_type)
PY
```

### Stage 3: Criterion Evaluation

**Purpose:** Evaluate every rubric criterion sequentially, require evidence-based reasoning, calculate the total score, and persist the result.

**Input:** Existing task and submission JSON artifacts, selected provider, and optional `--model-name` or `--test-mode`.

**Output:** `storage/evaluations/<submission-id>.json`, validated as `EvaluationReport`, with per-criterion scores, reasoning, evidence, and summary feedback.

**Verification:**

```bash
python main.py evaluate \
  --task-id task1 \
  --submission-id 'Product_BM_ДЗ1_Решение хорошее' \
  --provider openrouter
```

```bash
python - <<'PY'
from src.repository.evaluation_repository import EvaluationRepository

report = EvaluationRepository().load("Product_BM_ДЗ1_Решение хорошее")
assert report.criterion_results
assert 0 <= report.total_score <= report.max_total_score
assert all(
    0 <= result.assigned_score <= result.max_points
    and result.reasoning.strip()
    and result.evidence
    for result in report.criterion_results
)
print("Evaluation OK:", report.total_score, "/", report.max_total_score)
PY
```

### Stage 4: PDF Report Generation

**Purpose:** Render an existing evaluation JSON and its matching task JSON as a Russian-language PDF without reading raw submission files.

**Input:** An evaluation JSON path and optional output path.

**Output:** `storage/reports/<evaluation-stem>.pdf` by default.

**Verification:**

```bash
python main.py generate-pdf \
  --eval-json 'storage/evaluations/Product_Fraud_ДЗ2_Решение хорошее.json'
```

## 4. Key Functions & Usage Examples

### Configuration

```python
from src.config import AppConfig

config = AppConfig(
    llm_provider="openrouter",
    model_name="qwen/qwen-2.5-72b-instruct:free",
    test_mode=True,
)
print(config.effective_api_base)
print(config.model_chain)
```

### Task parsing and storage

```python
from src.config import AppConfig
from src.parsers.task_parser import TaskParser
from src.repository.task_repository import TaskRepository

rubric = TaskParser(AppConfig()).parse_task(
    "data/Product_Fraud_hw2.pdf",
    "productfraudhw2",
)
TaskRepository().save(rubric)
```

### Local and GitHub submission parsing

```python
from src.config import AppConfig
from src.parsers.submission_parser import SubmissionParser
from src.repository.submission_repository import SubmissionRepository

parser = SubmissionParser(AppConfig(), "productfraudhw2")
submission = parser.parse_submission(
    "data/Product_Fraud_ДЗ2_Решение хорошее.docx",
    "productfraudhw2",
)
SubmissionRepository().save(submission)

github_submission = parser.parse_github_repository(
    "https://github.com/ArtemCh101/test_repo"
)
SubmissionRepository().save(github_submission)
```

### Evaluation

```python
from src.config import AppConfig
from src.evaluator.grading_engine import GradingEngine
from src.repository.task_repository import TaskRepository
from src.repository.submission_repository import SubmissionRepository

config = AppConfig(llm_provider="openrouter")
rubric = TaskRepository().load("productfraudhw2")
submission = SubmissionRepository().load("test_repo")
report = GradingEngine(config).evaluate_submission(rubric, submission, config)
print(report.total_score, report.max_total_score)
```

### PDF generation

```python
from src.reports.pdf_generator import generate_evaluation_pdf

output_path = generate_evaluation_pdf(
    "storage/evaluations/test_repo.json",
    "storage/reports/test_repo.pdf",
)
print(output_path)
```
