"""Utilities to run Alembic migrations programmatically."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_head(db_path: Path) -> None:
    """Apply Alembic migrations up to head for the given SQLite database."""

    root_dir = Path(__file__).resolve().parents[4]
    alembic_ini = root_dir / "alembic.ini"
    alembic_dir = root_dir / "alembic"

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_dir))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
