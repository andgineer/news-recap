"""Common helpers for storage repositories."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine


def utc_now() -> datetime:
    """Current UTC timestamp."""

    return datetime.now(tz=UTC)


def from_iso(value: str) -> datetime:
    """Parse ISO datetime and ensure timezone-aware UTC fallback."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    """Create sqlite connection configured for row access by name."""

    connection = sqlite3.connect(db_path)
    _apply_sqlite_pragmas(connection, busy_timeout_ms=5000)
    connection.row_factory = sqlite3.Row
    return connection


def build_sqlite_engine(*, db_path: Path, busy_timeout_ms: int) -> Engine:
    """Build SQLAlchemy engine with consistent SQLite policy."""

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(
        db_url,
        connect_args={
            "check_same_thread": False,
            "timeout": max(1.0, busy_timeout_ms / 1000.0),
        },
        poolclass=NullPool,
    )
    event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _: _apply_sqlite_pragmas(
            dbapi_connection,
            busy_timeout_ms=busy_timeout_ms,
        ),
    )
    return engine


def connect_sqlite_with_policy(*, db_path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    """Create sqlite3 connection with the same policy as SQLAlchemy engine."""

    connection = sqlite3.connect(db_path)
    _apply_sqlite_pragmas(connection, busy_timeout_ms=busy_timeout_ms)
    connection.row_factory = sqlite3.Row
    return connection


def _apply_sqlite_pragmas(dbapi_connection: sqlite3.Connection, *, busy_timeout_ms: int) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute(f"PRAGMA busy_timeout = {max(1, busy_timeout_ms)}")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()
