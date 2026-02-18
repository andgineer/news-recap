"""Add ingestion run heartbeat for stale-run recovery."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260217_0005"
down_revision = "20260217_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE ingestion_runs
            SET heartbeat_at = COALESCE(heartbeat_at, finished_at, started_at, CURRENT_TIMESTAMP)
            """,
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "heartbeat_at")
