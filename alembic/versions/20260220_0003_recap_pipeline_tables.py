"""Add recap pipeline state tables."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260220_0003"
down_revision = "20260219_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recap_pipeline_runs",
        sa.Column("pipeline_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_step", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("pipeline_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_recap_pipeline_runs_user_date",
        "recap_pipeline_runs",
        ["user_id", "business_date"],
    )

    op.create_table(
        "recap_pipeline_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_id", sa.String(), nullable=False),
        sa.Column("step_name", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["recap_pipeline_runs.pipeline_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_recap_pipeline_tasks_pipeline",
        "recap_pipeline_tasks",
        ["pipeline_id"],
    )


def downgrade() -> None:
    op.drop_table("recap_pipeline_tasks")
    op.drop_table("recap_pipeline_runs")
