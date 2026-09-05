# Imported frontend

This directory was imported from `origin/kirillsanik-frontend` into `frontend/`.
It contains only the upstream Next.js UI, its assets, and Node configuration; no
upstream Python backend, Docker configuration, tests, or root documentation was
merged into this repository.

The frontend's default API base is `http://localhost:8000/api/v1`. Override it
when needed with `NEXT_PUBLIC_API_URL`:

```bash
cd frontend
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

The upstream UI was designed around a broader, separate API (including routes
such as authentication and courses). Those routes have not been added to or
imported into this repository's backend. The existing FastAPI endpoints and all
backend behavior remain authoritative.

The upstream `docs/` directory is preserved verbatim in
[`frontend/source-docs/`](frontend/source-docs/). Its original root README is
preserved below so that the incoming documentation is not lost.

## Upstream README snapshot

# AI Reviewer

PoC рабочего места ревьюера и методиста для проверки домашних заданий.

## Структура

- `frontend/` — Next.js, TypeScript, Tailwind CSS, TanStack Query/Table.
- `student-portal/` — отдельный Next.js-портал студента.
- `backend/` — FastAPI, SQLAlchemy, PostgreSQL, Celery.
- `spec/` — краткая продуктовая и техническая спецификация.

## Запуск через Docker

```bash
docker compose up --build
```

- Интерфейс ревьюера и методиста: http://localhost:3000
- Студенческий портал: http://localhost:3001
- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs

## Локальная разработка

Требуются Node.js 22 и Python 3.12.

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Во втором терминале:

```bash
cd frontend
npm install
npm run dev
```

В третьем терминале:

```bash
cd student-portal
npm install
npm run dev
```

Без `DATABASE_URL` backend использует локальную SQLite. PostgreSQL и Redis
поднимаются через Docker Compose.

## Реализованный сценарий

1. Вход или регистрация ревьюера/методиста.
2. Активные и завершённые курсы в виде карточек.
3. Домашние задания с личным или глобальным прогрессом.
4. Очередь работ, AI-черновик, ручное ревью и PDF.
5. Вопросы методисту, управление ревьюерами и редактирование критериев.
6. Отдельный студенческий портал: заявка на курс, зачисление, список ДЗ,
   баллы и отправка ссылки на работу.

Демо-аккаунты:

- ревьюер: `reviewer` / `reviewer`;
- методист: `methodist` / `methodist`.

AI-анализ сейчас детерминированный: это безопасная заглушка для проверки
workflow. Реальные GitHub, LLM, Google Sheets и Telegram подключаются через
переменные из `backend/.env.example` после выдачи тестовых доступов.

This snapshot documents the upstream project and may refer to files and services
that were intentionally not imported here.
