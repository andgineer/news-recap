"""Initial single-tenant multi-user ingestion schema (squashed baseline)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

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
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
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

    op.create_table(
        "articles",
        sa.Column("article_id", sa.String(), nullable=False),
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
        sa.Column("clean_text", sa.Text(), nullable=False),
        sa.Column("clean_text_chars", sa.Integer(), nullable=False),
        sa.Column("is_truncated", sa.Boolean(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fallback_key", sa.String(), nullable=True),
        sa.Column("last_processed_run_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("article_id"),
        sa.UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_articles_source_external",
        ),
    )

    op.create_table(
        "user_articles",
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "article_id", name="pk_user_articles"),
    )

    op.create_table(
        "article_external_ids",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_article_external_ids_source_external",
        ),
    )

    op.create_table(
        "articles_raw",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", name="uq_articles_raw_article"),
        sa.UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_articles_raw_source_external",
        ),
    )

    op.create_table(
        "article_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id",
            "model_name",
            name="uq_article_embeddings_article_model",
        ),
    )

    op.create_table(
        "article_resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("url_hash", sa.String(), nullable=False),
        sa.Column("url_canonical", sa.String(), nullable=False),
        sa.Column("fetch_status", sa.String(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
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

    op.create_table(
        "llm_tasks",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", sa.String(), nullable=True),
        sa.Column("last_exit_code", sa.Integer(), nullable=True),
        sa.Column("repair_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("input_manifest_path", sa.String(), nullable=False),
        sa.Column("output_path", sa.String(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )

    op.create_table(
        "llm_task_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status_from", sa.String(), nullable=True),
        sa.Column("status_to", sa.String(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["llm_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "llm_task_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["llm_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_articles_hash_published",
        "articles",
        ["source_name", "url_hash", "published_at"],
    )
    op.create_index(
        "uq_ingestion_runs_scope_source_running",
        "ingestion_runs",
        ["user_id", "source"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_articles_fallback_key",
        "articles",
        ["source_name", "fallback_key"],
        unique=True,
        sqlite_where=sa.text("fallback_key IS NOT NULL"),
    )
    op.create_index(
        "idx_user_articles_user_discovered",
        "user_articles",
        ["user_id", "discovered_at"],
    )
    op.create_index(
        "uq_article_resources_public_url_hash",
        "article_resources",
        ["url_hash"],
        unique=True,
        sqlite_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "uq_article_resources_private_user_url_hash",
        "article_resources",
        ["user_id", "url_hash"],
        unique=True,
        sqlite_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index("idx_article_resources_lookup", "article_resources", ["url_hash", "user_id"])
    op.create_index("idx_dedup_clusters_scope_run", "dedup_clusters", ["user_id", "run_id"])
    op.create_index("idx_article_dedup_scope_run", "article_dedup", ["user_id", "run_id"])
    op.create_index(
        "idx_llm_tasks_queue",
        "llm_tasks",
        ["user_id", "status", "priority", "run_after"],
    )
    op.create_index(
        "idx_llm_task_events_task_time",
        "llm_task_events",
        ["task_id", "created_at"],
    )
    op.create_index(
        "idx_llm_task_artifacts_task_kind",
        "llm_task_artifacts",
        ["task_id", "kind"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO users(user_id, display_name, created_at)
            VALUES ('default_user', 'Default User', CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO NOTHING
            """,
        ),
    )


def downgrade() -> None:
    op.drop_index("idx_llm_task_artifacts_task_kind", table_name="llm_task_artifacts")
    op.drop_index("idx_llm_task_events_task_time", table_name="llm_task_events")
    op.drop_index("idx_llm_tasks_queue", table_name="llm_tasks")
    op.drop_index("idx_article_dedup_scope_run", table_name="article_dedup")
    op.drop_index("idx_dedup_clusters_scope_run", table_name="dedup_clusters")
    op.drop_index("idx_article_resources_lookup", table_name="article_resources")
    op.drop_index("uq_article_resources_private_user_url_hash", table_name="article_resources")
    op.drop_index("uq_article_resources_public_url_hash", table_name="article_resources")
    op.drop_index("idx_user_articles_user_discovered", table_name="user_articles")
    op.drop_index("uq_articles_fallback_key", table_name="articles")
    op.drop_index("uq_ingestion_runs_scope_source_running", table_name="ingestion_runs")
    op.drop_index("idx_articles_hash_published", table_name="articles")
    op.drop_table("llm_task_artifacts")
    op.drop_table("llm_task_events")
    op.drop_table("llm_tasks")
    op.drop_table("article_dedup")
    op.drop_table("dedup_clusters")
    op.drop_table("article_resources")
    op.drop_table("article_embeddings")
    op.drop_table("articles_raw")
    op.drop_table("article_external_ids")
    op.drop_table("user_articles")
    op.drop_table("articles")
    op.drop_table("rss_processing_snapshots")
    op.drop_table("rss_feed_states")
    op.drop_table("ingestion_gaps")
    op.drop_table("ingestion_runs")
    op.drop_table("users")
