"""Common helpers for storage repositories."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


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
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection
