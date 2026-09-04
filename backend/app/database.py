import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ai_reviewer.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# create_all does not add columns to existing tables. Keep local/dev DBs usable
# after model changes without wiping registered users.
REQUIRED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "courses": (
        ("stream", "INTEGER DEFAULT 1"),
        ("active", "BOOLEAN DEFAULT 1"),
        ("cover_color", "VARCHAR(40) DEFAULT '#2563EB'"),
        ("students_count", "INTEGER DEFAULT 0"),
        ("description", "TEXT DEFAULT ''"),
        ("capacity", "INTEGER DEFAULT 30"),
    ),
    "assignments": (
        ("number", "INTEGER DEFAULT 1"),
        ("criteria_url", "VARCHAR(500) DEFAULT ''"),
    ),
    "assignment_reviewers": (
        ("user_id", "INTEGER"),
    ),
    "submissions": (
        ("student_user_id", "INTEGER"),
        ("reviewer_user_id", "INTEGER"),
        ("criterion_scores", "JSON"),
    ),
}


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in REQUIRED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
