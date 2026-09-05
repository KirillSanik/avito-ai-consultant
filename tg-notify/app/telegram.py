from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

_TIMEOUT = httpx.Timeout(40.0, connect=10.0)


class TelegramAPIError(Exception):
    def __init__(
        self,
        message: str,
        error_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after


class RateLimitedError(TelegramAPIError):
    pass


class PermanentTelegramError(TelegramAPIError):
    pass


def _api_url(method: str) -> str:
    token = settings.telegram_bot_token
    if not token:
        raise PermanentTelegramError("TELEGRAM_BOT_TOKEN is not set")
    return f"https://api.telegram.org/bot{token}/{method}"


def _raise_from_payload(payload: dict[str, Any], http_status: int) -> None:
    description = str(payload.get("description") or "Telegram API error")
    error_code = int(payload.get("error_code") or http_status)
    parameters = payload.get("parameters") or {}
    retry_after = parameters.get("retry_after")
    retry_after_int = int(retry_after) if retry_after is not None else None

    if error_code == 429 or retry_after_int is not None:
        raise RateLimitedError(
            description,
            error_code=error_code,
            retry_after=retry_after_int or 1,
        )
    if error_code in {400, 403, 404} or http_status in {400, 403, 404}:
        raise PermanentTelegramError(description, error_code=error_code)
    raise TelegramAPIError(description, error_code=error_code, retry_after=retry_after_int)


def _request(method: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=_TIMEOUT) as client:
        response = client.post(_api_url(method), json=json)
    try:
        payload = response.json()
    except ValueError as exc:
        if response.status_code >= 500:
            raise TelegramAPIError(
                f"Telegram HTTP {response.status_code}",
                error_code=response.status_code,
            ) from exc
        raise TelegramAPIError(f"Invalid Telegram response: HTTP {response.status_code}") from exc

    if not isinstance(payload, dict):
        raise TelegramAPIError(f"Unexpected Telegram payload: HTTP {response.status_code}")

    if response.status_code >= 500:
        raise TelegramAPIError(
            str(payload.get("description") or f"Telegram HTTP {response.status_code}"),
            error_code=int(payload.get("error_code") or response.status_code),
        )
    if response.status_code == 429 or not payload.get("ok", False):
        _raise_from_payload(payload, response.status_code)
    return payload


def send_message(chat_id: int, text: str) -> None:
    _request(
        "sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def get_updates(offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        params["offset"] = offset
    payload = _request("getUpdates", json=params)
    result = payload.get("result") or []
    return list(result)
