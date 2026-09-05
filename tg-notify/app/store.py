from __future__ import annotations

import re

from redis import Redis

from app.config import settings

NICK_RE = re.compile(r"^[a-z][a-z0-9_]{4,31}$")
USER_KEY = "tg:user:{nick}"
CHAT_KEY = "tg:chat:{chat_id}"
OFFSET_KEY = "tg:bot:offset"

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def ping() -> bool:
    return bool(get_redis().ping())


def normalize_nick(raw: str) -> str | None:
    nick = raw.strip().lstrip("@").lower()
    if not NICK_RE.fullmatch(nick):
        return None
    return nick


def save_user(nick: str, chat_id: int) -> None:
    redis = get_redis()
    nick = nick.lower().lstrip("@")
    previous = redis.get(CHAT_KEY.format(chat_id=chat_id))
    if previous and previous != nick:
        redis.delete(USER_KEY.format(nick=previous))
    redis.set(USER_KEY.format(nick=nick), str(chat_id))
    redis.set(CHAT_KEY.format(chat_id=chat_id), nick)


def get_chat_id(nick: str) -> int | None:
    value = get_redis().get(USER_KEY.format(nick=nick.lower().lstrip("@")))
    if value is None:
        return None
    return int(value)


def resolve_nicks(nicks: list[str]) -> tuple[list[str], list[str]]:
    known: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for nick in nicks:
        if nick in seen:
            continue
        seen.add(nick)
        if get_chat_id(nick) is None:
            unknown.append(nick)
        else:
            known.append(nick)
    return known, unknown


def get_offset() -> int | None:
    value = get_redis().get(OFFSET_KEY)
    if value is None:
        return None
    return int(value)


def set_offset(offset: int) -> None:
    get_redis().set(OFFSET_KEY, str(offset))
