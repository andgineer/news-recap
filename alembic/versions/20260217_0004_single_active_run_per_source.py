"""Enforce single active ingestion run per user and source."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260217_0004"
down_revision = "20260217_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the newest RUNNING row per (user_id, source), mark older duplicates as failed.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    run_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, source
                        ORDER BY started_at DESC, run_id DESC
                    ) AS rn
                FROM ingestion_runs
                WHERE status = 'running'
            )
            UPDATE ingestion_runs
            SET
                status = 'failed',
                finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                error_summary = COALESCE(
                    error_summary,
                    'Auto-closed during migration: duplicate running runs.'
                )
            WHERE run_id IN (SELECT run_id FROM ranked WHERE rn > 1)
            """,
        ),
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_runs_scope_source_running
            ON ingestion_runs (user_id, source)
            WHERE status = 'running'
            """,
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS uq_ingestion_runs_scope_source_running",
        ),
    )
