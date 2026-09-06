import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def send_telegram_notification(nicks: list[str], message: str) -> bool:
    recipients = [nick.strip() for nick in nicks if isinstance(nick, str) and nick.strip()]
    if not recipients:
        return False
    api_key = os.getenv("NOTIFY_API_KEY", "").strip()
    if not api_key:
        logger.warning("Telegram notifier is not configured")
        return False
    url = os.getenv("TG_NOTIFY_URL", "http://tg-notify:8010/notify")
    try:
        async with httpx.AsyncClient(timeout=240.0) as client:
            response = await client.post(
                url,
                json={"nicks": recipients, "message": message},
                headers={"X-API-Key": api_key},
            )
            response.raise_for_status()
            return True
    except Exception:
        logger.exception("Telegram notification request failed")
        return False
