"""Add RSS feed HTTP cache table."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260217_0002"
down_revision = "20260217_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_feed_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("feed_url", sa.String(), nullable=False),
        sa.Column("etag", sa.String(), nullable=True),
        sa.Column("last_modified", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_name",
            "feed_url",
            name="uq_rss_feed_states_scope_source_url",
        ),
    )


def downgrade() -> None:
    op.drop_table("rss_feed_states")
