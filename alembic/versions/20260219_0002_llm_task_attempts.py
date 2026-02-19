"""Add per-attempt LLM execution telemetry table."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260219_0002"
down_revision = "20260217_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_task_attempts",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("profile", sa.String(), nullable=True),
        sa.Column("command_template_hash", sa.String(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("timed_out", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_class", sa.String(), nullable=True),
        sa.Column("attempt_failure_code", sa.String(), nullable=True),
        sa.Column("error_summary_sanitized", sa.Text(), nullable=True),
        sa.Column("stdout_preview_sanitized", sa.Text(), nullable=True),
        sa.Column("stderr_preview_sanitized", sa.Text(), nullable=True),
        sa.Column("output_chars", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_status", sa.String(), nullable=True),
        sa.Column("usage_source", sa.String(), nullable=True),
        sa.Column("usage_parser_version", sa.String(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["llm_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "task_id",
            "attempt_no",
            name="uq_llm_task_attempts_task_attempt_no",
        ),
    )
    op.create_index(
        "idx_llm_task_attempts_scope_time",
        "llm_task_attempts",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_llm_task_attempts_task_type_time",
        "llm_task_attempts",
        ["task_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_llm_task_attempts_failure_time",
        "llm_task_attempts",
        ["failure_class", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_llm_task_attempts_agent_model_time",
        "llm_task_attempts",
        ["agent", "model", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_llm_task_attempts_agent_model_time", table_name="llm_task_attempts")
    op.drop_index("idx_llm_task_attempts_failure_time", table_name="llm_task_attempts")
    op.drop_index("idx_llm_task_attempts_task_type_time", table_name="llm_task_attempts")
    op.drop_index("idx_llm_task_attempts_scope_time", table_name="llm_task_attempts")
    op.drop_table("llm_task_attempts")
