"""Synchronous SQLAlchemy session setup, initialized during FastAPI lifespan."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, inspect, text
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
    _migrate_user_columns(_engine)
    _migrate_course_columns(_engine)


def _migrate_user_columns(engine: Engine) -> None:
    """Add demo-auth fields to databases created before the auth UI existed."""
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    additions = {
        "password": "VARCHAR(256) NOT NULL DEFAULT ''",
        "first_name": "VARCHAR(128) NOT NULL DEFAULT ''",
        "last_name": "VARCHAR(128) NOT NULL DEFAULT ''",
        "telegram": "VARCHAR(256) NOT NULL DEFAULT ''",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))


def _migrate_course_columns(engine: Engine) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("courses")}
    additions = {
        "year": "INTEGER NOT NULL DEFAULT 2026",
        "cohort": "VARCHAR(128) NOT NULL DEFAULT ''",
        "stream": "INTEGER NOT NULL DEFAULT 1",
        "active": "BOOLEAN NOT NULL DEFAULT 1",
        "cover_color": "VARCHAR(16) NOT NULL DEFAULT '#3B6EF5'",
        "students_count": "INTEGER NOT NULL DEFAULT 0",
        "description": "VARCHAR(4000) NOT NULL DEFAULT ''",
        "capacity": "INTEGER NOT NULL DEFAULT 30",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE courses ADD COLUMN {name} {definition}"))


def get_session() -> Generator[Session, None, None]:
    if _session_factory is None:
        raise RuntimeError("Database is not initialized")
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def open_session() -> Session:
    """Open a short-lived session for startup initialization tasks."""
    if _session_factory is None:
        raise RuntimeError("Database is not initialized")
    return _session_factory()
