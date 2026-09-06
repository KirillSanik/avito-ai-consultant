from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.store import normalize_nick, ping, resolve_nicks
from app.tasks import send_notifications

app = FastAPI(title="tg-notify", version="0.1.0")


class NotifyRequest(BaseModel):
    nicks: list[str] = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4096)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("message must not be empty")
        return text


class NotifyResponse(BaseModel):
    queued: int
    unknown: list[str]
    job_id: str | None


class HealthResponse(BaseModel):
    ok: bool
    redis: bool
    telegram_token: bool


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if not settings.notify_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NOTIFY_API_KEY is not configured",
        )
    if x_api_key != settings.notify_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    redis_ok = False
    try:
        redis_ok = ping()
    except Exception:
        redis_ok = False
    token_ok = bool(settings.telegram_bot_token)
    return HealthResponse(ok=redis_ok and token_ok, redis=redis_ok, telegram_token=token_ok)


@app.post(
    "/notify",
    response_model=NotifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
def notify(payload: NotifyRequest) -> NotifyResponse:
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TELEGRAM_BOT_TOKEN is not configured",
        )

    normalized: list[str] = []
    invalid: list[str] = []
    for raw in payload.nicks:
        nick = normalize_nick(raw)
        if nick is None:
            invalid.append(raw)
        else:
            normalized.append(nick)

    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid Telegram nicks: {', '.join(invalid)}",
        )

    try:
        known, unknown = resolve_nicks(normalized)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable",
        ) from exc
    if not known:
        return NotifyResponse(queued=0, unknown=unknown, job_id=None)

    try:
        result = send_notifications.delay(known, payload.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Queue is unavailable",
        ) from exc
    return NotifyResponse(queued=len(known), unknown=unknown, job_id=result.id)
