import os
import sys
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import User


TARGET_USERNAME = "artemchebykin"
MESSAGE = "Тестовое уведомление для ревьюера ArtemChebykin"


def main() -> int:
    notify_url = os.getenv("TG_NOTIFY_URL", "").strip()
    api_key = os.getenv("TG_NOTIFY_API_KEY", "").strip()
    try:
        with SessionLocal() as db:
            user = db.scalar(
                select(User).where(func.lower(User.telegram_username) == TARGET_USERNAME)
            )
            if user is None:
                print(f"User @{TARGET_USERNAME} was not found")
                return 1
            username = (user.telegram_username or user.telegram or "").strip().lstrip("@").lower()
            chat_id = str(user.tg_id) if user.tg_id is not None else None
            print({"user_id": user.id, "username": username, "chat_id": chat_id})
    except SQLAlchemyError as exc:
        print(f"Database lookup failed: {exc}")
        return 1
    if not notify_url or not api_key:
        print("TG_NOTIFY_URL and TG_NOTIFY_API_KEY must be configured")
        return 1
    endpoint = notify_url if notify_url.endswith("/send-message") else f"{notify_url.rstrip('/')}/send-message"
    payload = {"chat_id": chat_id, "username": username or None, "message": MESSAGE}
    try:
        response = httpx.post(endpoint, json=payload, headers={"X-API-Key": api_key}, timeout=15.0)
    except httpx.HTTPError as exc:
        print(f"Notification request failed: {exc}")
        return 1
    print(f"status={response.status_code} body={response.text}")
    return 0 if response.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
