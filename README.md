# Automated Homework Reviewer

Автоматизированный пайплайн проверки учебных работ. Он извлекает требования из задания, разбирает локальную сдачу или GitHub-репозиторий и оценивает работу по критериям через локальную LLM.

## Архитектура

Три последовательных этапа:

1. **Ingest Task**: PDF задания → `TaskRubric` с полными инструкциями, критериями, ограничениями и максимальными баллами.
2. **Parse Submission**: локальный `.xlsx`, `.docx` или `.pdf`, либо GitHub-репозиторий → `SubmissionData` с текстом, таблицами, ссылками и деревом файлов.
3. **Evaluate**: `TaskRubric` + `SubmissionData` → последовательная проверка каждого критерия → `EvaluationReport`.

Баллы по каждому критерию валидируются Pydantic-схемой. Итоговый балл рассчитывается в Python как сумма оценок, а не генерируется моделью.

## Технологии

- Python 3.10+, Click, Pydantic v2
- Instructor и Ollama с Qwen2.5
- pdfplumber, python-docx, openpyxl
- Git CLI для shallow-clone GitHub-репозиториев
- python-dotenv для переменных окружения

## Установка

Нужны Python 3.10+ и Ollama. Установите зависимости и загрузите модели:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull qwen2.5:1.5b
ollama serve
```

Для доступа к приватным GitHub-репозиториям создайте `.env` на основе `.env.example`:

```dotenv
GITHUB_TOKEN=your_github_token_here
```

Токен добавляется только к HTTPS URL во время `git clone`; публичные репозитории работают без него.

## CLI

### 1. Загрузка задания

```bash
python main.py ingest-task --file <path_to_task.pdf> --task-id <id> [--test-mode]
```

### 2. Разбор локальной сдачи

```bash
python main.py parse-submission --file <path_to_submission> --task-id <id>
```

Поддерживаются `.xlsx`, `.docx` и `.pdf`.

### 2. Разбор GitHub-репозитория

```bash
python main.py parse-submission --url <repo_url> --task-id <id>
```

Укажите ровно один источник: `--file` или `--url`. При разборе репозитория игнорируются служебные каталоги, наборы данных, бинарные файлы, файлы крупнее 1 МБ и нормализованные названия описаний задания. Оставшиеся файлы объединяются с явными границами `=== FILE: ... ===`.

### 3. Оценивание

Передайте новый файл:

```bash
python main.py evaluate --task-id <id> --submission-file <path_to_submission> [--test-mode]
```

Или ранее сохранённую сдачу, включая GitHub-сдачу:

```bash
python main.py evaluate --task-id <id> --submission-id <submission_id> [--test-mode]
```

## Test mode

`--test-mode` предназначен для ограниченного оборудования:

- выбирает лёгкую модель `qwen2.5:1.5b` по умолчанию; допустима явная замена на `qwen2.5:3b`;
- передаёт Ollama `num_ctx=4096`;
- ограничивает каждый LLM payload до `max_chars=12000` символов.

Обычный режим использует `qwen2.5:7b`, стандартное контекстное окно и не обрезает текст.

## Хранение результатов

```text
storage/
├── tasks/<task_id>.json
├── submissions/<submission_id>.json
└── evaluations/<submission_id>.json
```

## Python API

Основные точки интеграции:

```python
from src.config import AppConfig
from src.evaluator.grading_engine import GradingEngine
from src.parsers.submission_parser import SubmissionParser
from src.parsers.task_parser import TaskParser

config = AppConfig(test_mode=True)
rubric = TaskParser(config).parse_task("task.pdf", "task-1")
submission = SubmissionParser(config, "task-1").parse_github_repository(
    "https://github.com/owner/repository.git"
)
report = GradingEngine(config).evaluate_submission(rubric, submission, config)
```
