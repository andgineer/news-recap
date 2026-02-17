"""Add crash-safe RSS processing snapshots table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260217_0003"
down_revision = "20260217_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_processing_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("feed_set_hash", sa.String(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("next_cursor", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_name",
            "feed_set_hash",
            name="uq_rss_processing_snapshots_scope_source_feed_set",
        ),
    )


def downgrade() -> None:
    op.drop_table("rss_processing_snapshots")
