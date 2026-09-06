# Telegram-уведомления

## Что должно быть установлено

- Docker и Docker Compose
- Telegram-бот от [@BotFather](https://t.me/BotFather) (`/newbot`)

## Настройка

```bash
cp .env.example .env
```

В `.env` укажите:

- `TELEGRAM_BOT_TOKEN` — токен бота
- `NOTIFY_API_KEY` — ключ для вызова API
- `REDIS_URL` — для Docker можно не менять

Получатель один раз пишет боту `/start`. Без этого сообщение по нику не уйдёт.

## Запуск

Из папки `tg-notify`:

```bash
docker compose up --build
```

API: `http://localhost:8010`

## Вызов

```bash
curl -s -X POST http://localhost:8010/notify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -d '{"nicks":["KirillSanik"],"message":"Дедлайн по ДЗ-3 завтра в 18:00"}'
```

`nicks` — ники в Telegram, `message` — текст. Ответ сразу `202`. Если ник в `unknown` — человек не нажал `/start`.
