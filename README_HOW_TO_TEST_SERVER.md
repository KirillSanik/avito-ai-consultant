# How to Test the Homework Reviewer Server

This guide reflects the current FastAPI route signatures in `src/app.py` and
the SQLAlchemy models in `src/common/db/models.py`. API request bodies use
`multipart/form-data`; they are not JSON bodies.

## Prerequisites and server launch

Install dependencies and configure an LLM before launching. By default,
`LLM_PROVIDER` is `openrouter`, so `OPENROUTER_API_KEY` is required unless you
explicitly select an Ollama-compatible endpoint.

```bash
uv sync

# In a separate terminal, start the local provider once.
ollama serve
ollama pull qwen2.5-coder

# In the server terminal, select local Ollama.
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

The code default is `APP_HOST=127.0.0.1`, `APP_PORT=8000`. If `.env` or the
environment sets `APP_PORT=8765`, use port `8765` instead. Verify the chosen
port and inspect the OpenAPI schema:

```bash
curl -I http://127.0.0.1:8000/docs
curl http://127.0.0.1:8000/openapi.json
```

The commands below use a shell variable, so they work with either port:

```bash
export BASE_URL=http://127.0.0.1:8000
```

At startup the service creates database tables and `storage/tasks`,
`storage/submissions`, and `storage/reports`. The default database is SQLite
at `storage/app.db` unless `DATABASE_URL` is configured differently.

### OpenRouter primary with local Ollama quota fallback

Keep `ollama serve` running, put `OPENROUTER_API_KEY` in the uncommitted
`.env`, then start the service with:

```bash
export LLM_PROVIDER=openrouter
export AI_DETECTOR_LLM_PROVIDER=openrouter
export MODEL_NAME=google/gemma-4-31b-it:free
export AI_DETECTOR_LLM_MODEL=google/gemma-4-31b-it:free
export OLLAMA_FALLBACK_BASE_URL=http://localhost:11434/v1
export OLLAMA_FALLBACK_MODEL=qwen2.5-coder
uv run main.py
```

The cloud order is Gemma → Nemotron → MiniMax → Poolside → GLM →
`openrouter/free`. A daily-free-tier OpenRouter 429 bypasses the remaining
cloud models and switches to Ollama; ordinary transient 429s are retried.

## Exact request schema

### `POST /api/v1/users/register`

Required form fields:

| Field | Type | Accepted value |
| --- | --- | --- |
| `user_id` | string | Non-empty filename-safe ID; this becomes database `User.id`. |
| `role` | enum string | Lowercase exactly: `methodist`, `student`, or `reviewer`. |
| `name` | string | Display name. |

The response uses `id`, not `user_id`: `{ "id": "…", "role": "student", "name": "…" }`.

### `POST /api/v1/tasks`

Required form fields: `course_id` (string) and `title` (string). Supply
**exactly one** task source:

- `file`: uploaded `.pdf` or `.docx`; or
- `url`: `http`/`https` URL whose path ends in `.pdf` or `.docx`.

`course_id` is a string ID. There is currently no course-creation endpoint:
the route creates a course with `id=course_id` and `title=course_id` when it
does not already exist. The server generates the task UUID returned as `id`.

### `POST /api/v1/submissions`

Required form fields: `task_id` (the UUID from task creation) and `student_id`
(a registered user whose lowercase `role` is exactly `student`). Supply
**exactly one** source:

- `repo_url`: repository URL string; or
- `file`: uploaded solution file.

The server generates `submission_id`. Its persisted status is internally one
of lowercase `pending`, `processing`, `completed`, or `failed`; successful
responses return `completed`.

### Evaluation reads

- `GET /api/v1/evaluations?submission_id=<string>` requires the query parameter
  named exactly `submission_id`.
- `GET /api/v1/evaluations/{submission_id}/pdf` takes the same identifier as a
  path segment and returns `application/pdf`.
- `GET /health` returns `{ "status": "ok" }`.
- `GET /api/v1/tasks/{task_id}` returns the stored task/rubric.
- `GET /api/v1/submissions/{submission_id}` returns the submission status.

## Step-by-step curl test

### 1. Register users

All three role values are lowercase. Only the student is required to create a
submission, but these commands verify the complete enum.

```bash
curl --fail-with-body -X POST "$BASE_URL/api/v1/users/register" \
  -F user_id=methodist-1 -F role=methodist -F 'name=Methodist One'

curl --fail-with-body -X POST "$BASE_URL/api/v1/users/register" \
  -F user_id=student-1 -F role=student -F 'name=Student One'

curl --fail-with-body -X POST "$BASE_URL/api/v1/users/register" \
  -F user_id=reviewer-1 -F role=reviewer -F 'name=Reviewer One'
```

Each succeeds with HTTP `201`. Repeat requests with the same `user_id` return
HTTP `409`.

### 2. Create a task from a local file

Use a real PDF or DOCX: the server parses it into a rubric using the LLM.

```bash
curl --fail-with-body -X POST "$BASE_URL/api/v1/tasks" \
  -F course_id=course-1 \
  -F 'title=Python homework' \
  -F 'file=@./assignment.docx'
```

The HTTP `201` JSON includes `id`, `course_id`, `title`, and `rubric_json`.
Copy the returned UUID into the next command:

```bash
export TASK_ID='paste-task-id-here'
```

To use a hosted task instead, replace the file part with exactly one `url`:

```bash
curl --fail-with-body -X POST "$BASE_URL/api/v1/tasks" \
  -F course_id=course-1 \
  -F 'title=Python homework' \
  -F url=https://example.org/assignment.pdf
```

### 3. Submit a repository URL

```bash
curl --fail-with-body -X POST "$BASE_URL/api/v1/submissions" \
  -F task_id="$TASK_ID" \
  -F student_id=student-1 \
  -F repo_url=https://github.com/example/student-homework.git
```

Or upload a local solution file instead. Do not include `repo_url` in this
request:

```bash
curl --fail-with-body -X POST "$BASE_URL/api/v1/submissions" \
  -F task_id="$TASK_ID" \
  -F student_id=student-1 \
  -F 'file=@./solution.py'
```

Successful submissions return HTTP `201` with `submission_id`, lowercase
`status` (`completed`), `review_json`, and `pdf_url`.

```bash
export SUBMISSION_ID='paste-submission-id-here'
```

### 4. Retrieve review JSON

```bash
curl --fail-with-body \
  "$BASE_URL/api/v1/evaluations?submission_id=$SUBMISSION_ID"
```

The response has `submission_id`, the persisted `review_json`, and `pdf_url`.

### 5. Download the PDF

```bash
curl --fail-with-body -OJ \
  "$BASE_URL/api/v1/evaluations/$SUBMISSION_ID/pdf"
```

The file is also persisted by the server under `storage/reports/`.

## LLM versus offline capabilities

| Operation | Works without a live LLM? | Notes |
| --- | --- | --- |
| Server startup | No, with default settings | Default OpenRouter mode requires `OPENROUTER_API_KEY` while building clients. Configure Ollama or OpenRouter first. |
| `POST /api/v1/users/register` | Yes, after server startup | Database write only. |
| `POST /api/v1/tasks` | No | It stores the raw file locally, extracts text, then calls the LLM to create `rubric_json`. A failed LLM parse does not create the task record. |
| `POST /api/v1/submissions` | No | It persists the submission, then runs AI detection and LLM grading, generates a PDF, and stores an evaluation. A failure leaves the submission in `failed` status. Repository submissions also require `git` and repository access. |
| `GET /api/v1/evaluations` | Yes | Reads an existing evaluation from the database. |
| `GET /api/v1/evaluations/{submission_id}/pdf` | Yes | Serves an existing persisted PDF. |

For an offline deterministic integration check that replaces only external LLM
calls, run:

```bash
uv run pytest -s tests/test_server_verification.py

# Entire offline suite; no API key, Ollama, or network required.
uv run pytest -q

# Opt-in live tests: use the configured OpenRouter primary and real data files.
RUN_LIVE_OPENROUTER=1 uv run pytest -s tests/integration/test_live_openrouter_data.py
RUN_LIVE_OPENROUTER=1 uv run pytest -s tests/integration/test_live_http_endpoints.py
```
