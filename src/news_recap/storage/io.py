"""File-based storage utilities: atomic writes, daily partitions, GC."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TypeVar

import msgspec

T = TypeVar("T")


def utc_now() -> datetime:
    """Current UTC timestamp."""
    return datetime.now(tz=UTC)


def atomic_write(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically via temp + rename.

    Uses ``mkstemp`` to avoid the TOCTOU race inherent in ``mktemp``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def save_msgspec(path: Path, obj: object) -> None:
    """Encode *obj* as JSON and atomically write to *path*."""
    atomic_write(path, msgspec.json.encode(obj))


def load_msgspec(path: Path, typ: type[T]) -> T:
    """Load and decode a JSON file into *typ*."""
    return msgspec.json.decode(path.read_bytes(), type=typ)


def day_key(dt: datetime | None = None) -> str:
    """Return local-timezone date string ``YYYY-MM-DD``.

    Without *dt*, returns today in the machine's timezone.
    With *dt*, converts to local timezone first.

    >>> day_key(datetime(2026, 2, 19, 12, 0, tzinfo=UTC))  # doctest: +SKIP
    '2026-02-19'
    """
    if dt is None:
        return date.today().isoformat()
    return dt.astimezone().date().isoformat()


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def gc_old_days(data_dir: Path, *, keep_days: int = 7) -> list[Path]:
    """Delete daily partition files outside the *keep_days* retention window.

    With ``keep_days=7`` and today = Feb 19, keeps Feb 13..Feb 19 (7 days)
    and deletes Feb 12 and older.  Returns list of deleted paths (both
    article files and resource cache directories).
    """
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    deleted: list[Path] = []

    ingestion_dir = data_dir / "ingestion"
    if ingestion_dir.exists():
        for f in ingestion_dir.glob("articles-*.json"):
            day_str = f.stem.removeprefix("articles-")
            if day_str <= cutoff:
                f.unlink()
                deleted.append(f)

    resources_dir = data_dir / "resources"
    if resources_dir.exists():
        for d in resources_dir.iterdir():
            if d.is_dir() and _DATE_RE.fullmatch(d.name) and d.name <= cutoff:
                shutil.rmtree(d)
                deleted.append(d)

    return deleted
