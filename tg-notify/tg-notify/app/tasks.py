from __future__ import annotations

import logging
import time

import httpx

from app.celery_app import celery_app
from app.store import get_chat_id
from app.telegram import PermanentTelegramError, RateLimitedError, TelegramAPIError, send_message

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=8, name="app.tasks.send_notifications")
def send_notifications(self, nicks: list[str], message: str) -> dict[str, list[str]]:
    remaining = list(nicks)
    sent: list[str] = []
    skipped: list[str] = []

    while remaining:
        nick = remaining[0]
        chat_id = get_chat_id(nick)
        if chat_id is None:
            logger.warning("No chat_id for nick %s, skip", nick)
            skipped.append(nick)
            remaining.pop(0)
            continue
        try:
            send_message(chat_id, message)
        except RateLimitedError as exc:
            countdown = max(1, exc.retry_after or 1)
            logger.warning("Telegram rate limit, retry in %ss, remaining=%s", countdown, remaining)
            raise self.retry(exc=exc, countdown=countdown, args=[remaining, message]) from exc
        except PermanentTelegramError:
            logger.exception("Permanent Telegram error for nick %s", nick)
            skipped.append(nick)
            remaining.pop(0)
            continue
        except (TelegramAPIError, httpx.RequestError) as exc:
            countdown = min(60, 2 ** max(self.request.retries, 0))
            logger.warning("Transient Telegram error for nick %s, retry in %ss", nick, countdown)
            raise self.retry(exc=exc, countdown=countdown, args=[remaining, message]) from exc

        sent.append(nick)
        remaining.pop(0)
        if remaining:
            time.sleep(0.05)

    return {"sent": sent, "skipped": skipped}
