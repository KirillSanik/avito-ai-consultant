# avito-ai-consultant

AI-консультант по домашним заданиям: единый FastAPI-сервис, который за один
запрос **детектирует AI-генерацию кода** и **оценивает работу по критериям
условия**, плюс click-CLI `homework-reviewer` для прогона каждого этапа
отдельно (без сервера).

## Unified project quick start

The project is a FastAPI backend (`src/`) with a Next.js frontend
(`frontend/`). The backend stores users, courses, tasks, uploaded files, and
reports locally in `storage/`; the frontend calls `http://localhost:8000/api/v1`.

### Prerequisites

- Python 3.10+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js 18+ with `npm`

### Start the backend

```bash
uv sync
uv run main.py
```

### Start the frontend

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

Open `http://localhost:3000`. FastAPI documentation is at
`http://localhost:8000/docs`.

### Default demo accounts

| Role | Login | Password |
|------|-------|----------|
| Methodist | `methodist` | `methodist` |
| Reviewer | `reviewer` | `reviewer` |
| Students | `student1` … `student5` | `password` |

At startup, all five demo students are enrolled in every existing course, so
course cards immediately show their actual student count.

### What initializes automatically

`uv run main.py` starts FastAPI on `APP_HOST:APP_PORT` (default
`127.0.0.1:8000`). During the application lifespan it:

1. Creates `storage/tasks`, `storage/submissions`, and `storage/reports`.
2. Creates the configured SQLAlchemy database (`DATABASE_URL`), defaulting to
   `storage/app.db`, and applies additive schema migrations for existing SQLite
   databases.
3. Seeds the demo methodist, reviewer, and five student accounts.
4. Seeds sample courses/homework, enrolls demo students in every course, and
   initializes zero-progress records for each homework.

No manual database command is required on a new device. To use an existing
PostgreSQL instance, set `DATABASE_URL` in `.env` before starting the server.

### Setup on another device

```bash
git clone <repository-url>
cd avito-ai-consultant
cp .env.example .env
uv sync
uv run main.py
```

In a second terminal:

```bash
cd avito-ai-consultant/frontend
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

For a different host or LAN deployment, set `APP_HOST=0.0.0.0`, replace
`localhost` in `NEXT_PUBLIC_API_URL` with the server's reachable address, and
allow ports 8000 and 3000 through the device firewall. Configure
`OPENROUTER_API_KEY` for hosted LLM reviews, or run Ollama locally with
`ollama serve` and `ollama pull qwen2.5-coder` for the local fallback.

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
| LLM | Ollama/OpenAI-совместимый сервер на `http://localhost:11434/v1` и/или ключ OpenRouter | оценка |

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

| Переменная | Дефолт | Действие |
|------------|---------|----------|
| `OPENROUTER_API_KEY` | — | Обязателен, когда `LLM_PROVIDER=openrouter`. |
| `LLM_PROVIDER` | `openrouter` | Основной провайдер ревьюера: `openrouter` или `ollama`. |
| `MODEL_NAME` | `google/gemma-4-31b-it:free` | Первая модель OpenRouter либо локальная модель Ollama. |
| `API_BASE` | провайдер-зависимый | Адрес основного OpenAI-совместимого API; для Ollama: `http://localhost:11434/v1`. |
| `AI_DETECTOR_LLM_PROVIDER` | `local` | Провайдер детектора: `openrouter` или `local`. |
| `AI_DETECTOR_LLM_MODEL` | `google/gemma-4-31b-it:free` | Модель детектора. |
| `AI_DETECTOR_LLM_BASE_URL` | провайдер-зависимый | Для локального детектора: `http://localhost:11434/v1`. |
| `OLLAMA_FALLBACK_BASE_URL` | `http://localhost:11434/v1` | Независимый локальный fallback после суточной квоты OpenRouter. |
| `OLLAMA_FALLBACK_MODEL` | `qwen2.5-coder` | Модель Ollama для quota fallback. |
| `DATABASE_URL` | `sqlite:///./storage/app.db` | SQLAlchemy URL базы данных. |
| `STORAGE_DIR` | `./storage` | Корень персистентных файлов. |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Адрес Uvicorn. |

Цепочка OpenRouter при `LLM_PROVIDER=openrouter`:

```text
google/gemma-4-31b-it:free → nvidia/nemotron-3-super-120b-a12b:free →
minimax/minimax-m3:free → poolside/laguna-s-2.1:free →
z-ai/glm-5.2:free → openrouter/free
```

При `429` с признаком суточной free-tier квоты сервис сразу пропускает
оставшиеся модели OpenRouter и вызывает локальный Ollama fallback. Обычные
временные 429 продолжают использовать стандартные ретраи.

## Запуск сервиса

```bash
uv run main.py
# → FastAPI на http://127.0.0.1:8000
```

### Локальный Ollama

В отдельном терминале установите и запустите модель:

```bash
ollama serve
ollama pull qwen2.5-coder
```

Затем в терминале сервиса:

```bash
export LLM_PROVIDER=ollama
export API_BASE=http://localhost:11434/v1
export MODEL_NAME=qwen2.5-coder
export AI_DETECTOR_LLM_PROVIDER=local
export AI_DETECTOR_LLM_BASE_URL=http://localhost:11434/v1
export AI_DETECTOR_LLM_MODEL=qwen2.5-coder
export OLLAMA_FALLBACK_BASE_URL=http://localhost:11434/v1
export OLLAMA_FALLBACK_MODEL=qwen2.5-coder
uv run main.py
```

Для OpenRouter укажите `OPENROUTER_API_KEY` в локальном `.env`, установите
`LLM_PROVIDER=openrouter` и `AI_DETECTOR_LLM_PROVIDER=openrouter`. Ollama
остаётся доступен для автоматического quota fallback.

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

# Реальные OpenRouter-тесты не запускаются по умолчанию и требуют ключа.
RUN_LIVE_OPENROUTER=1 uv run pytest -s tests/integration/test_live_openrouter_data.py
RUN_LIVE_OPENROUTER=1 uv run pytest -s tests/integration/test_live_http_endpoints.py
```
