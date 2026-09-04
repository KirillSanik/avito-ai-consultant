# avito-ai-consultant

Инструменты AI-консультанта по домашним заданиям: два фиче-пакета над общим слоем.

| Пакет | Назначение | Форма |
|-------|------------|-------|
| `src/ai_detector/` | Детекция AI-генерации кода в репозиториях с решениями (вердикт «Светофор»: `green`/`yellow`/`red`) | async-библиотека |
| `src/homework_reviewer/` | 3-этапный ревьюер ДЗ: разбор PDF-задания → парсинг сдачи (xlsx/docx/pdf/GitHub) → покритериальная LLM-оценка + PDF-отчёт | click-CLI `homework-reviewer` |
| `src/common/` | Общие сущности: конфиг, git-клонирование, выбор файлов репозитория, PDF-извлечение, JSON-хранилища, LLM-клиент и устойчивость к сбоям (resilience) | слой общих сущностей |

Документация:
- `docs/ai-detector.md` — модуль детекции (API, ошибки, env).
- `docs/architecture.md` — техническое задание детектора + схема слоёв.
- `docs/product/` — продуктовые документы ревьюера (MVP, сценарии, риски).
- `specs/` — спецификации (spec-kit).
- `.specify/memory/constitution.md` — конституция проекта (обязательные принципы).

## Prerequisites

| Зависимость | Требование | Зачем |
|-------------|------------|-------|
| Python | ≥ 3.10 | `requires-python` в `pyproject.toml` |
| `uv` | последняя стабильная | управление окружением и зависимостями |
| `git` CLI | установлен и доступен в PATH | клонирование репозиториев (без GitHub API) |
| LLM | локальный OpenAI-совместимый сервер (детектор) и/или ключ OpenRouter (ревьюер) | оценка |

## Установка

```bash
uv sync
```

Создаст `.venv` по `pyproject.toml` и зафиксированному `uv.lock`; CLI ставится как
`homework-reviewer`.

## Переменные окружения

| Переменная | Обязательна | Действие |
|------------|------------|----------|
| `OPENROUTER_API_KEY` | только для ревьюера с провайдером `openrouter` | ключ LLM |
| `GITHUB_TOKEN` | только для приватных репозиториев | токен клонирования (оба модуля) |
| `AI_DETECTOR_GIT_TOKEN` | нет | переопределение токена детектора (приоритет над `GITHUB_TOKEN`) |
| `AI_DETECTOR_LLM_MODEL` | нет (дефолт — константа пакета) | имя модели детектора |

Шаблон — `.env.example`.

## Использование

### ai_detector (библиотека)

```python
import asyncio
from openai import AsyncOpenAI
from ai_detector import AIDetectionService

async def main() -> None:
    client = AsyncOpenAI(base_url="http://127.0.0.1:8000/v1", api_key="not-set")
    service = AIDetectionService(client)
    result = await service.analyze(
        task_criteria="Реализовать LRU-кэш, O(1) get/put, не использовать OrderedDict",
        repo_url="https://github.com/student/lru-hw.git",
    )
    print(result.status, result.confidence, result.reasoning)

asyncio.run(main())
```

Подробности (ошибки, контракт) — в `docs/ai-detector.md`.

### homework_reviewer (CLI)

```bash
# 1. Разобрать PDF-задание и сохранить рубрику
uv run homework-reviewer ingest-task --file "data/Задание.pdf" --task-id task1

# 2. Разобрать сдачу (файл или GitHub-репозиторий)
uv run homework-reviewer parse-submission --file "data/решение.xlsx" --task-id task1
uv run homework-reviewer parse-submission --url https://github.com/student/hw --task-id task1

# 3. Оценить по критериям (опционально — PDF-отчёт)
uv run homework-reviewer evaluate --task-id task1 --submission-id <id> --pdf
```

Состояние (JSON) пишется в `storage/{tasks,submissions,evaluations}/`, PDF-отчёты — в
`storage/reports/`; оба каталога git-игнорируются.

## Тестирование

```bash
uv run pytest
```

Pytest + pytest-asyncio, coverage-gate `--cov-fail-under=30`; ruff — `uv run ruff check src tests`.
