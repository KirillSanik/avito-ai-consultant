# AI Reviewer

PoC рабочего места ревьюера и методиста для проверки домашних заданий.

## Структура

- `frontend/` — Next.js, TypeScript, Tailwind CSS, TanStack Query/Table.
- `backend/` — FastAPI, SQLAlchemy, PostgreSQL, Celery.
- `spec/` — краткая продуктовая и техническая спецификация.

## Запуск через Docker

```bash
docker compose up --build
```

- Интерфейс: http://localhost:3000
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

Без `DATABASE_URL` backend использует локальную SQLite. PostgreSQL и Redis
поднимаются через Docker Compose.

## Реализованный сценарий

1. Демо-вход под ролью ревьюера или методиста.
2. Выбор курса и домашнего задания.
3. Очередь работ и AI-черновик проверки.
4. Ручное редактирование результата и формирование PDF.
5. Dashboard нагрузки и редактирование критериев методистом.

AI-анализ сейчас детерминированный: это безопасная заглушка для проверки
workflow. Реальные GitHub, LLM, Google Sheets и Telegram подключаются через
переменные из `backend/.env.example` после выдачи тестовых доступов.
