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
