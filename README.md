# avito-ai-consultant

AI-консультант по домашним заданиям: единый FastAPI-сервис, который за один
запрос **детектирует AI-генерацию кода** и **оценивает работу по критериям
условия**, плюс click-CLI `homework-reviewer` для прогона каждого этапа
отдельно (без сервера).

## Пакеты

| Пакет | Назначение |
|-------|------------|
| `src/app.py` + `src/core/` | FastAPI-сервис: единственный эндпоинт `POST /review`; `core.pipeline.Pipeline` оркеструет «парсинг условия → клонирование → параллельные оценки → агрегация» |
| `src/ai_detector/` | Детекция AI-генерации кода (вердикт «Светофор»: `green`/`yellow`/`red`); может использоваться как async-библиотека |
| `src/homework_reviewer/` | Ревьюер ДЗ: парсинг условия и сдачи (файл/GitHub), покритериальная LLM-оценка, PDF-отчёт; CLI `homework-reviewer` |
| `src/common/` | Общий слой: типизированные настройки (`.env`), LLM-клиенты с устойчивостью к сбоям (цепочка моделей), общие pydantic-модели, парсеры условия (PDF/DOCX/XLSX → рубрика), промпты |

## Как обрабатывается запрос `POST /review`

1. **Парсинг условия** (`common.parsers`) — текст из загруженного PDF/DOCX/XLSX
   и LLM-структурирование в `TaskRubric` (regex-fallback при сбое LLM); ровно
   один раз на запрос.
2. **Клонирование** (`core.repo_clone`) — одна временная копия репозитория через
   `git` (без GitHub API).
3. **Параллельные оценки** (`asyncio.gather`) — детекция AI-генерации ∥
   покритериальная оценка.
4. **Очистка** — temp-каталог удаляется в `finally` (успех, ошибка или отмена).
5. **Ответ** — `ReviewResponse`: агрегация обоих вердиктов.

## Документация

- `docs/ai-detector.md` — модуль детекции (API, ошибки, env).
- `docs/architecture.md` — техническое задание + схема слоёв.
- `docs/plan-merge-homework-reviewer-core.md`, `docs/plan.md`, `docs/tasks.md` —
  план и задачи слияния ревьюера.
- `docs/product/` — продуктовые документы ревьюера (MVP, сценарии, риски).
- `.specify/memory/constitution.md` — конституция проекта (обязательные принципы).

## Prerequisites

| Зависимость | Требование | Зачем |
|-------------|------------|-------|
| Python | ≥ 3.10 (`.python-version` — 3.13) | `requires-python` в `pyproject.toml` |
| `uv` | последняя стабильная | управление окружением и зависимостями |
| `git` CLI | установлен и доступен в PATH | клонирование репозиториев (без GitHub API) |
| LLM | локальный OpenAI-совместимый сервер (текущий `.env`: `localhost:8075`) и/или ключ OpenRouter | оценка |

## Установка

```bash
uv sync
```

Создаст `.venv` по `pyproject.toml` и зафиксированному `uv.lock`; CLI ставится
как `homework-reviewer`.

## Переменные окружения

Читаются из окружения и `.env` (шаблон — `.env.example`), схема —
`src/common/settings.py`. Секреты (ключи, токены) в README и в коммитимом
`.env.example` не хранятся — только из локального `.env`/окружения.

| Переменная | Обязательна | Дефолт (код) | В текущем `.env` | Действие |
|------------|-------------|--------------|------------------|----------|
| `OPENROUTER_API_KEY` | да, только при провайдере `openrouter` | — | не задан (обойдётся без ключа) | ключ LLM OpenRouter |
| `LLM_PROVIDER` | нет | `openrouter` | `ollama` | LLM ревьюера: `openrouter` \| `ollama` |
| `API_BASE` | нет | — (эффективно: OpenRouter / `http://localhost:11434/v1` по провайдеру) | `http://localhost:8075/v1` | адрес LLM-сервера ревьюера |
| `API_KEY` | нет | — | не задан | ключ LLM-сервера ревьюера |
| `MODEL_NAME` | нет | `qwen/qwen-2.5-72b-instruct:free` | `qwen3.8-27b-fp8` | модель ревьюера; при сбое на `openrouter` — резервная цепочка (`common.llm.OPENROUTER_FREE_MODELS`) |
| `AI_DETECTOR_LLM_PROVIDER` | нет | `local` | — (т.е. `local`) | LLM детектора: `local` (OpenAI-совместимый сервер) \| `openrouter` |
| `AI_DETECTOR_LLM_MODEL` | указать при `local` | `local-model` (заглушка) | `qwen3.8-27b-fp8` | модель детектора: имя модели на локальном сервере |
| `AI_DETECTOR_LLM_BASE_URL` | нет | — (эффективно: OpenRouter / `http://localhost:11434/v1`) | `http://localhost:8075/v1` | адрес LLM-сервера детектора |
| `AI_DETECTOR_LLM_API_KEY` | нет | — (заглушка `not-set`) | не задан | ключ LLM-сервера детектора |
| `LLM_MAX_TOKENS` | нет | `16384` | — | `max_tokens` LLM-запросов |
| `LLM_DISABLE_THINKING` | нет | `true` | — | отключает reasoning-режим Qwen3 (ускоряет ответ) |
| `GITHUB_TOKEN` | только для приватных репозиториев | — | не задан (публичные репо) | токен клонирования (оба модуля) |
| `AI_DETECTOR_GIT_TOKEN` | нет | — | — | переопределение токена детектора (приоритет над `GITHUB_TOKEN`) |
| `APP_HOST` | нет | `127.0.0.1` | — | хост запуска uvicorn |
| `APP_PORT` | нет | `8000` | `8765` | порт запуска uvicorn |
| `APP_WORKERS` | нет | `1` | — | число workers uvicorn |
| `TEST_MODE` | нет | `false` | — | тест-режим: усечение входного текста |

## Запуск сервиса

```bash
uv run main.py
# → FastAPI на http://127.0.0.1:8765
```

С текущим `.env` inline-переменные не нужны: ревьюер и детектор оба работают
через локальный LLM-сервер `http://localhost:8075/v1` (провайдер `ollama`,
модель `qwen3.8-27b-fp8`), порт сервиса — `8765`.

Чтобы переключиться на OpenRouter: `LLM_PROVIDER=openrouter` +
`OPENROUTER_API_KEY` (и при необходимости `MODEL_NAME`,
`AI_DETECTOR_LLM_PROVIDER=openrouter`).

### `POST /review`

```bash
curl -X POST http://127.0.0.1:8765/review \
  -F "repo_url=https://github.com/student/hw" \
  -F "task_file=@data/Product_BM_ДЗ1_условия.pdf"
```

- `repo_url` (form) — URL репозитория со сдачей.
- `task_file` (upload) — условие задания: `.pdf`, `.docx` или `.xlsx`.

**Ответ** — `ReviewResponse` (схема в `src/common/models.py`):

```json
{
  "repo_url": "https://github.com/student/hw",
  "task_id": "Product_BM_ДЗ1_условия",
  "ai_assessment": {
    "status": "green",
    "confidence": 0.0,
    "reasoning": "...",
    "ai_indicators": [],
    "human_indicators": []
  },
  "evaluation": {
    "task_id": "task1",
    "submission_id": "hw",
    "total_score": 0.0,
    "max_total_score": 0.0,
    "criterion_results": [
      {
        "criterion_id": "c1",
        "criterion_name": "...",
        "assigned_score": 0.0,
        "max_points": 0.0,
        "reasoning": "...",
        "evidence": []
      }
    ],
    "summary_feedback": "..."
  }
}
```

**Коды ошибок**: `422` — репозиторий недоступен, неподдерживаемый формат
условия или сбой парсинга; `502` — сбой LLM (детектор/ревьюер/разбор условия);
`503` — сервис ещё не готов; `500` — прочее.

### Демо-прогон

```bash
uv run python demo/run_review.py [base_url]
```

Отправляет `POST /review` (демо-репозиторий из `demo/web_hw_url.txt` + условие
`demo/web_hw_tz.docx`), сохраняет и валидирует ответ. Сервер должен уже работать
(по умолчанию `http://127.0.0.1:8765`).

## CLI (этапы отдельно, без сервера)

```bash
# 1. Разобрать условие (PDF/DOCX/XLSX) → TaskRubric в JSON (storage/tasks/)
uv run homework-reviewer ingest-task --file "data/Задание.pdf" --task-id task1

# 2. Разобрать сдачу (файл или GitHub-репозиторий) → JSON (storage/submissions/)
uv run homework-reviewer parse-submission --file "data/решение.xlsx" --task-id task1
uv run homework-reviewer parse-submission --url https://github.com/student/hw --task-id task1

# 3. Оценить по критериям → отчёт в JSON (storage/evaluations/); --pdf — ещё и PDF (storage/reports/)
uv run homework-reviewer evaluate --task-id task1 --submission-id <id> --pdf

# 4. PDF прямо из JSON ИИ-ревью
uv run homework-reviewer generate-pdf --eval-json storage/evaluations/<id>.json --output report.pdf
```

Общие флаги: `-p/--provider {openrouter,ollama}`, `--api-base`, `--api-key`,
`--model`, `--test-mode`. Состояние (JSON) пишется в
`storage/{tasks,submissions,evaluations}/`, PDF-отчёты — в `storage/reports/`;
каталог `storage/` git-игнорируется.

## ai_detector как библиотека

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

## Тестирование

```bash
uv run pytest                      # pytest + pytest-asyncio, coverage-gate --cov-fail-under=30
uv run ruff check src tests        # линтер
```
