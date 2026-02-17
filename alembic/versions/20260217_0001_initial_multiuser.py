"""Initial single-tenant multi-user ingestion schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260217_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dedup_clusters_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dedup_duplicates_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gaps_opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "ingestion_gaps",
        sa.Column("gap_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("from_cursor_or_time", sa.String(), nullable=True),
        sa.Column("to_cursor_or_time", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=False),
        sa.Column("retry_after", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gap_id"),
    )

    op.create_table(
        "articles_raw",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_name",
            "external_id",
            name="uq_articles_raw_scope_source_external",
        ),
    )

    op.create_table(
        "articles",
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("url_canonical", sa.String(), nullable=False),
        sa.Column("url_hash", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source_domain", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language_detected", sa.String(), nullable=False),
        sa.Column("content_raw", sa.Text(), nullable=True),
        sa.Column("summary_raw", sa.Text(), nullable=True),
        sa.Column("is_full_content", sa.Boolean(), nullable=False),
        sa.Column("needs_enrichment", sa.Boolean(), nullable=False),
        sa.Column("clean_text", sa.Text(), nullable=False),
        sa.Column("clean_text_chars", sa.Integer(), nullable=False),
        sa.Column("is_truncated", sa.Boolean(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fallback_key", sa.String(), nullable=True),
        sa.Column("last_processed_run_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("article_id"),
        sa.UniqueConstraint(
            "user_id",
            "source_name",
            "external_id",
            name="uq_articles_scope_source_external",
        ),
    )

    op.create_table(
        "article_external_ids",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_name",
            "external_id",
            name="uq_article_external_ids_scope_source_external",
        ),
    )

    op.create_table(
        "article_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "article_id",
            "model_name",
            name="uq_article_embeddings_scope_article_model",
        ),
    )

    op.create_table(
        "dedup_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("cluster_id", sa.String(), nullable=False),
        sa.Column("representative_article_id", sa.String(), nullable=False),
        sa.Column("alt_sources_json", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["representative_article_id"],
            ["articles.article_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "run_id",
            "cluster_id",
            name="uq_dedup_clusters_scope_run_cluster",
        ),
    )

    op.create_table(
        "article_dedup",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("cluster_id", sa.String(), nullable=False),
        sa.Column("is_representative", sa.Boolean(), nullable=False),
        sa.Column("similarity_to_rep", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "run_id", "cluster_id"],
            ["dedup_clusters.user_id", "dedup_clusters.run_id", "dedup_clusters.cluster_id"],
            ondelete="CASCADE",
            name="fk_article_dedup_cluster_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "run_id",
            "article_id",
            name="uq_article_dedup_scope_run_article",
        ),
    )

    op.create_index(
        "idx_articles_scope_hash_published",
        "articles",
        ["user_id", "source_name", "url_hash", "published_at"],
    )
    op.create_index(
        "uq_articles_scope_fallback_key",
        "articles",
        ["user_id", "source_name", "fallback_key"],
        unique=True,
        sqlite_where=sa.text("fallback_key IS NOT NULL"),
    )
    op.create_index("idx_dedup_clusters_scope_run", "dedup_clusters", ["user_id", "run_id"])
    op.create_index("idx_article_dedup_scope_run", "article_dedup", ["user_id", "run_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO users(user_id, display_name, created_at)
            VALUES ('default_user', 'Default User', CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_article_dedup_scope_run", table_name="article_dedup")
    op.drop_index("idx_dedup_clusters_scope_run", table_name="dedup_clusters")
    op.drop_index("uq_articles_scope_fallback_key", table_name="articles")
    op.drop_index("idx_articles_scope_hash_published", table_name="articles")
    op.drop_table("article_dedup")
    op.drop_table("dedup_clusters")
    op.drop_table("article_embeddings")
    op.drop_table("article_external_ids")
    op.drop_table("articles")
    op.drop_table("articles_raw")
    op.drop_table("ingestion_gaps")
    op.drop_table("ingestion_runs")
    op.drop_table("users")
