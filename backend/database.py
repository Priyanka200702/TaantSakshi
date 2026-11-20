"""
backend/database.py
Database engine and session management for TantSaakshi.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import DATABASE_URL

# SQLite connection with thread safety check disabled for FastAPI dependency injection
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

# Enforce SQLite foreign keys and WAL mode for reliability and concurrency
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator:
    """FastAPI dependency for yielding database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables defined in models."""
    import backend.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)


# Columns added after the first release. create_all() never alters existing
# tables, so older databases get them here (all nullable, no data change).
_LATE_COLUMNS = {
    "sarees": {
        "weave_json": "TEXT",
        "closeup_path": "VARCHAR(512)",
        "spacing_json": "TEXT",
        "declared_json": "TEXT",
        "listing_json": "TEXT",
    },
}


def add_missing_columns(bind) -> list[str]:
    """Add any missing late columns. Returns the 'table.column' names added."""
    from sqlalchemy import inspect, text

    added: list[str] = []
    insp = inspect(bind)
    with bind.begin() as conn:
        for table, cols in _LATE_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, sql_type in cols.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}"))
                    added.append(f"{table}.{col}")
    return added
