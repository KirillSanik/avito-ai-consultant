"""Synchronous SQLAlchemy session setup, initialized during FastAPI lifespan."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from common.db.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_db(database_url: str) -> None:
    """Create the configured database and all tables; safe to call at each startup."""
    global _engine, _session_factory
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(_engine)


def get_session() -> Generator[Session, None, None]:
    if _session_factory is None:
        raise RuntimeError("Database is not initialized")
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
