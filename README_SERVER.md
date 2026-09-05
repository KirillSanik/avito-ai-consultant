# Homework Reviewer Server

This guide deploys the FastAPI service that persists users, tasks, submissions,
evaluations, and PDF reports. The server initializes its database and storage
directories at startup.

## Prerequisites

Choose one deployment method:

- **Recommended:** Docker Desktop (Docker Engine plus Docker Compose v2).
- **Local development:** Python 3.10+ and [uv](https://docs.astral.sh/uv/).

For actual AI reviews, `git` must be available and the selected LLM provider
must be reachable. The API itself is served by FastAPI/Uvicorn.

## Environment configuration

Create an uncommitted `.env` in the project root. Important values are:

```dotenv
# SQLite for local use; Docker Compose overrides this with PostgreSQL.
DATABASE_URL=sqlite:///./storage/app.db

# Local Ollama configuration.
LLM_PROVIDER=ollama
API_BASE=http://localhost:11434/v1
MODEL_NAME=qwen2.5-coder
AI_DETECTOR_LLM_PROVIDER=local
AI_DETECTOR_LLM_BASE_URL=http://localhost:11434/v1
AI_DETECTOR_LLM_MODEL=qwen2.5-coder
OLLAMA_FALLBACK_BASE_URL=http://localhost:11434/v1
OLLAMA_FALLBACK_MODEL=qwen2.5-coder
```

`DATABASE_URL` accepts any SQLAlchemy connection string. For PostgreSQL use,
for example, `postgresql+psycopg://user:password@host:5432/database`.
`API_BASE` and `MODEL_NAME` select the OpenAI-compatible LLM endpoint/model
used for rubric parsing and criterion grading. The detector has separate
`AI_DETECTOR_LLM_*` settings when it must use a different endpoint; see
`.env.example` for all available settings.

For OpenRouter, set `LLM_PROVIDER=openrouter`,
`AI_DETECTOR_LLM_PROVIDER=openrouter`, and add `OPENROUTER_API_KEY` only to
the uncommitted `.env`. The model order is:

```text
google/gemma-4-31b-it:free → nvidia/nemotron-3-super-120b-a12b:free →
minimax/minimax-m3:free → poolside/laguna-s-2.1:free →
z-ai/glm-5.2:free → openrouter/free
```

An account-level OpenRouter 429 containing a daily-free-tier quota marker
bypasses the remaining cloud models and sends the request to
`OLLAMA_FALLBACK_BASE_URL`. Other temporary 429s retain cloud retry behavior.

Never commit `.env` or real API keys.

## Method A — Docker Compose (recommended)

Start the complete stack:

```bash
docker compose up --build
```

Compose starts:

- `web`: the FastAPI service on `http://localhost:8000`;
- `db`: PostgreSQL 16, with a named persistent volume (`postgres_data`);
- `./storage` mounted into the service at `/app/storage` for task uploads,
  solution uploads, reports, and any SQLite fallback database.

For detached operation, use `docker compose up --build -d`. Stop it with
`docker compose down`; add `-v` only when intentionally deleting PostgreSQL
data. Configure LLM credentials/endpoints in `.env` before starting a real
review workload. From Linux, adjust the `host.docker.internal` endpoint in
`docker-compose.yml` if the LLM is not reachable from the container.

## Method B — local development (SQLite)

Start Ollama and pull the configured local fallback model in one terminal:

```bash
ollama serve
ollama pull qwen2.5-coder
```

In another terminal, start the server:

```bash
uv sync
uv run main.py
```

The default service URL is `http://127.0.0.1:8000`. On FastAPI startup it
creates `./storage/tasks`, `./storage/submissions`, `./storage/reports`, and
the SQLite database `./storage/app.db` automatically. Set `APP_HOST` and
`APP_PORT` in `.env` to change the bind address.

## API quick reference

All write endpoints use `multipart/form-data`.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/users/register` | Create a `methodist`, `student`, or `reviewer`. |
| `POST /api/v1/tasks` | Upload a PDF/DOCX task (or provide a URL); parses and stores its rubric. |
| `POST /api/v1/submissions` | Submit a repository URL or uploaded solution; runs review and creates a PDF. |
| `GET /health` | Liveness response, `{ "status": "ok" }`. |
| `GET /api/v1/tasks/{task_id}` | Retrieve persisted task and rubric. |
| `GET /api/v1/submissions/{submission_id}` | Retrieve persisted submission and status. |
| `GET /api/v1/evaluations?submission_id=...` | Retrieve persisted review JSON and PDF URL. |
| `GET /api/v1/evaluations/{submission_id}/pdf` | Download the PDF report. |

Open interactive OpenAPI documentation at `/docs`.

### Minimal curl workflow

Register the required student (the task endpoint creates a course automatically
when its `course_id` is new):

```bash
curl -X POST http://localhost:8000/api/v1/users/register \
  -F user_id=student-1 -F role=student -F 'name=Student One'
```

Create a task and retain the returned `id` as `TASK_ID`:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -F course_id=course-1 \
  -F 'title=Python homework' \
  -F 'file=@./assignment.docx'
```

Submit a Git repository, then retain `submission_id` as `SUBMISSION_ID`:

```bash
curl -X POST http://localhost:8000/api/v1/submissions \
  -F task_id="$TASK_ID" \
  -F student_id=student-1 \
  -F repo_url=https://github.com/example/student-homework.git
```

An uploaded solution works too:

```bash
curl -X POST http://localhost:8000/api/v1/submissions \
  -F task_id="$TASK_ID" \
  -F student_id=student-1 \
  -F 'file=@./solution.py'
```

Retrieve the persisted evaluation and its PDF:

```bash
curl "http://localhost:8000/api/v1/evaluations?submission_id=$SUBMISSION_ID"
curl -OJ "http://localhost:8000/api/v1/evaluations/$SUBMISSION_ID/pdf"
```

## Verification

The deterministic server verification exercises FastAPI startup, SQLite table
creation, upload persistence, evaluation persistence, PDF generation, and PDF
download without requiring a live LLM:

```bash
uv run pytest -s tests/test_server_verification.py

# Entire offline suite; live OpenRouter tests remain skipped.
uv run pytest -q

# Explicit real OpenRouter flows; requires configured OPENROUTER_API_KEY.
RUN_LIVE_OPENROUTER=1 uv run pytest -s tests/integration/test_live_openrouter_data.py
RUN_LIVE_OPENROUTER=1 uv run pytest -s tests/integration/test_live_http_endpoints.py
```
