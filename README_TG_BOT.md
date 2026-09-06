# Telegram notifications

The `tg-notify` service is an additive notification gateway. It resolves Telegram
handles from the shared Redis instance and queues messages for delivery. The
gateway does not alter backend API routes or evaluation data.

Configure these values in the root `.env` file (use your own local secrets):

```dotenv
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
NOTIFY_API_KEY=your_custom_secret_key_here
REDIS_URL=redis://redis:6379/0
```

Start the gateway and its delivery workers with:

```bash
docker compose up -d tg-notify tg-notify-worker tg-notify-bot
```

The protected notification endpoint is available at `http://localhost:8010/notify`.
Send the configured key in the `X-API-Key` header. `/health` reports Redis and
Telegram configuration status.

The backend Celery beat service checks hourly for assignments due within 24 hours,
notifies enrolled students without a submission, and deduplicates each
assignment/student reminder in Redis.
