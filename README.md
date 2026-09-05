# AI Reviewer

PoC рабочего места ревьюера и методиста для проверки домашних заданий.

## Структура

- `frontend/` — Next.js, TypeScript, Tailwind CSS, TanStack Query/Table.
- `student-portal/` — отдельный Next.js-портал студента.
- `backend/` — FastAPI, SQLAlchemy, PostgreSQL, Celery.
- `spec/` — краткая продуктовая и техническая спецификация.

## Запуск через Docker

Требуется Docker Engine с Docker Compose v2. Для AI-проверки укажите
`POLZA_API_KEY` в корневом файле `.env`:

```bash
cp backend/.env.example .env
```

Для демонстрации интерфейса без запуска AI-проверки ключ можно оставить пустым.
Для реальной проверки GitHub-репозиториев задайте также `GITHUB_TOKEN` (нужен для
приватных репозиториев). Затем выполните:

```bash
docker compose up --build
```

- Интерфейс ревьюера и методиста: http://localhost:3000
- Студенческий портал: http://localhost:3001
- API: http://localhost:8000
- OpenAPI: http://localhost:8000/docs

Compose поднимает PostgreSQL, Redis, FastAPI API, Celery worker, интерфейс
ревьюера и студенческий портал. Данные PostgreSQL и сохранённые загруженные
файлы/PDF-отчёты находятся в Docker volumes. Остановить сервисы можно через
`docker compose down`; добавить `-v` следует только если нужно удалить и данные.

## Локальная разработка

Требуются Node.js 22 и Python 3.12.

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
set -a
source .env
set +a
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
поднимаются через Docker Compose. Для локального запуска Celery в четвёртом
терминале используйте:

```bash
cd backend
source .venv/bin/activate
set -a
source .env
set +a
celery -A app.tasks.celery_app worker --loglevel=info
```

## AI-проверка работ

Методист загружает файл задания PDF, DOCX, XLSX или Markdown через
`POST /api/assignments/{assignment_id}/task-file`. Backend извлекает текст,
сохраняет структурированную рубрику и версию критериев. Ревьюер запускает
`POST /api/submissions/{submission_id}/ai-draft`; это ставит Celery-задачу в
очередь. После завершения в деталях сдачи доступны статус, структурированный
отчёт, AI-оценка происхождения работы и постоянный PDF по адресу
`/api/submissions/{submission_id}/report.pdf`.

Для запуска реальной оценки доступны два варианта LLM-провайдера:

- `LLM_PROVIDER=cloud` (по умолчанию) — polza.ai, требуются `POLZA_API_KEY`
  и доступная модель `LLM_MODEL` (например, `qwen/qwen3.8-flash`).
- `LLM_PROVIDER=local` — локальный OpenAI-совместимый Ollama-сервер,
  при этом задаются `OLLAMA_BASE_URL` и `OLLAMA_MODEL`.

`GITHUB_TOKEN` является опциональным для публичных и необходимым для
приватных репозиториев.

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

AI-черновик выполняется асинхронно в Celery. Ручное ревью остаётся источником
окончательного решения и не изменяет существующие права доступа или очередь
ревьюеров.

## Логи действий и диагностика

Frontend записывает события нажатий, загрузок, запросов API и скачивания отчётов
в консоль браузера с префиксом `[ReviewDesk]`. Откройте DevTools (F12) →
**Console**, включите сохранение сообщений и отфильтруйте по `ReviewDesk`.

Последние 200 событий также сохраняются в Local Storage текущего frontend-origin
под ключом `reviewdesk.activity.log`. Их можно посмотреть в DevTools →
**Application/Storage → Local Storage** или выполнить в Console:

```js
JSON.parse(localStorage.getItem("reviewdesk.activity.log") || "[]")
```

Для очистки истории используйте:

```js
localStorage.removeItem("reviewdesk.activity.log")
```

Backend и Celery пишут переходы загрузки задания и AI-оценки в стандартный
Python-лог. При Docker-запуске смотрите их так:

```bash
docker compose logs -f backend worker
```

Для последних сообщений без режима follow:

```bash
docker compose logs --tail=200 backend worker
```

В локальном запуске эти сообщения появляются в терминалах `uvicorn` и Celery;
события имеют имена вроде `evaluation.enqueue.accepted` и
`evaluation.task.completed`.
