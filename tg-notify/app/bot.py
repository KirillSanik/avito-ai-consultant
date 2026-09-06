from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.store import get_offset, save_user, set_offset
from app.telegram import send_message, get_updates

logger = logging.getLogger(__name__)

WELCOME = (
    "Готово. Ник @{nick} привязан к этому чату — уведомления будут приходить сюда."
)
NEED_USERNAME = (
    "Чтобы получать уведомления, задайте username в настройках Telegram "
    "и снова нажмите /start."
)


def _command_name(text: str) -> str:
    first = text.split()[0] if text else ""
    return first.split("@", 1)[0]


def handle_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    text = str(message.get("text") or "")
    from_user = message.get("from") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    username = from_user.get("username")
    if username:
        save_user(username, int(chat_id))

    if _command_name(text) != "/start":
        return

    if not username:
        send_message(int(chat_id), NEED_USERNAME)
        return

    send_message(int(chat_id), WELCOME.format(nick=username))
    logger.info("Linked @%s -> chat_id=%s", username, chat_id)


def run() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Bot polling started")
    offset = get_offset()

    while True:
        try:
            updates = get_updates(offset=offset, timeout=25)
            for update in updates:
                offset = int(update["update_id"]) + 1
                set_offset(offset)
                try:
                    handle_update(update)
                except Exception:
                    logger.exception("Failed to handle update %s", update.get("update_id"))
        except Exception:
            logger.exception("Polling error")
            time.sleep(3)


if __name__ == "__main__":
    run()
