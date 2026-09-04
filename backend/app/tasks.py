import asyncio
import os

from aiogram import Bot
from celery import Celery


celery_app = Celery(
    "ai_reviewer",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",
)


@celery_app.task(name="notifications.deadline_reminder")
def deadline_reminder(course: str, assignment: str, deadline: str) -> dict[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {
            "status": "skipped",
            "reason": "Telegram credentials are not configured",
        }

    message = (
        f"Напоминание о дедлайне\n\n"
        f"Курс: {course}\n"
        f"Задание: {assignment}\n"
        f"Дедлайн: {deadline}"
    )

    async def send() -> None:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=message)

    asyncio.run(send())
    return {
        "status": "sent",
        "course": course,
        "assignment": assignment,
        "deadline": deadline,
    }
