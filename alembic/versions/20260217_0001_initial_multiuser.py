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
        "user_story_definitions",
        sa.Column("story_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("target_language", sa.String(), nullable=False, server_default="en"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("story_id"),
        sa.UniqueConstraint(
            "user_id",
            "name",
            name="uq_user_story_definitions_scope_name",
        ),
        sa.UniqueConstraint(
            "user_id",
            "story_id",
            name="uq_user_story_definitions_scope_story",
        ),
    )

    op.create_table(
        "story_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=False),
        sa.Column("story_id", sa.String(), nullable=True),
        sa.Column("story_key", sa.String(), nullable=False),
        sa.Column("assignment_type", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.article_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "story_id"],
            ["user_story_definitions.user_id", "user_story_definitions.story_id"],
            ondelete="SET NULL",
            name="fk_story_assignments_story_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "business_date",
            "article_id",
            name="uq_story_assignments_scope_date_article",
        ),
    )

    op.create_table(
        "daily_story_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("story_id", sa.String(), nullable=True),
        sa.Column("story_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("continuity_key", sa.String(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "story_id"],
            ["user_story_definitions.user_id", "user_story_definitions.story_id"],
            ondelete="SET NULL",
            name="fk_daily_story_snapshots_story_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "business_date",
            "story_key",
            name="uq_daily_story_snapshots_scope_date_key",
        ),
    )

    op.create_table(
        "monitor_questions",
        sa.Column("monitor_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cadence", sa.String(), nullable=False, server_default="daily"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("monitor_id"),
        sa.UniqueConstraint(
            "user_id",
            "monitor_id",
            name="uq_monitor_questions_scope_monitor",
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

    op.create_table(
        "output_citation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("article_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["llm_tasks.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "task_id",
            "source_id",
            name="uq_output_citation_snapshots_scope_task_source",
        ),
    )

    op.create_table(
        "user_outputs",
        sa.Column("output_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("story_id", sa.String(), nullable=True),
        sa.Column("monitor_id", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["llm_tasks.task_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("output_id"),
        sa.UniqueConstraint(
            "user_id",
            "output_id",
            name="uq_user_outputs_scope_output",
        ),
        sa.UniqueConstraint(
            "user_id",
            "kind",
            "request_id",
            name="uq_user_outputs_scope_kind_request",
        ),
    )

    op.create_table(
        "user_output_blocks",
        sa.Column("block_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("output_id", sa.String(), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "output_id"],
            ["user_outputs.user_id", "user_outputs.output_id"],
            ondelete="CASCADE",
            name="fk_user_output_blocks_output_scope",
        ),
        sa.PrimaryKeyConstraint("block_id"),
        sa.UniqueConstraint(
            "user_id",
            "block_id",
            name="uq_user_output_blocks_scope_block",
        ),
        sa.UniqueConstraint(
            "user_id",
            "output_id",
            "block_id",
            name="uq_user_output_blocks_scope_output_block",
        ),
        sa.UniqueConstraint(
            "user_id",
            "output_id",
            "block_order",
            name="uq_user_output_blocks_scope_order",
        ),
    )

    op.create_table(
        "read_state_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("output_id", sa.String(), nullable=False),
        sa.Column("output_block_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "output_id"],
            ["user_outputs.user_id", "user_outputs.output_id"],
            ondelete="CASCADE",
            name="fk_read_state_events_output_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "output_block_id"],
            ["user_output_blocks.user_id", "user_output_blocks.block_id"],
            ondelete="CASCADE",
            name="fk_read_state_events_block_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "output_id", "output_block_id"],
            [
                "user_output_blocks.user_id",
                "user_output_blocks.output_id",
                "user_output_blocks.block_id",
            ],
            ondelete="CASCADE",
            name="fk_read_state_events_output_block_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "output_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default_user", nullable=False),
        sa.Column("output_id", sa.String(), nullable=False),
        sa.Column("output_block_id", sa.Integer(), nullable=True),
        sa.Column("feedback_type", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "output_id"],
            ["user_outputs.user_id", "user_outputs.output_id"],
            ondelete="CASCADE",
            name="fk_output_feedback_output_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "output_block_id"],
            ["user_output_blocks.user_id", "user_output_blocks.block_id"],
            ondelete="CASCADE",
            name="fk_output_feedback_block_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "output_id", "output_block_id"],
            [
                "user_output_blocks.user_id",
                "user_output_blocks.output_id",
                "user_output_blocks.block_id",
            ],
            ondelete="CASCADE",
            name="fk_output_feedback_output_block_scope",
        ),
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
    op.create_index(
        "idx_output_citation_snapshots_scope_task",
        "output_citation_snapshots",
        ["user_id", "task_id"],
    )
    op.create_index(
        "idx_story_assignments_scope_story",
        "story_assignments",
        ["user_id", "business_date", "story_key"],
    )
    op.create_index(
        "idx_user_output_blocks_scope_output",
        "user_output_blocks",
        ["user_id", "output_id"],
    )
    op.create_index(
        "idx_read_state_events_scope_time",
        "read_state_events",
        ["user_id", "created_at"],
    )
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
        "idx_output_feedback_scope_time",
        "output_feedback",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_llm_task_attempts_scope_time",
        "llm_task_attempts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_llm_task_attempts_task_type_time",
        "llm_task_attempts",
        ["task_type", "created_at"],
    )
    op.create_index(
        "idx_llm_task_attempts_failure_time",
        "llm_task_attempts",
        ["failure_class", "created_at"],
    )
    op.create_index(
        "idx_llm_task_attempts_agent_model_time",
        "llm_task_attempts",
        ["agent", "model", "created_at"],
    )
    op.create_index(
        "uq_user_outputs_daily_highlights",
        "user_outputs",
        ["user_id", "kind", "business_date"],
        unique=True,
        sqlite_where=sa.text(
            "kind = 'highlights' "
            "AND story_id IS NULL "
            "AND monitor_id IS NULL "
            "AND request_id IS NULL",
        ),
    )
    op.create_index(
        "uq_user_outputs_story_detail",
        "user_outputs",
        ["user_id", "kind", "business_date", "story_id"],
        unique=True,
        sqlite_where=sa.text("story_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_outputs_monitor_answer",
        "user_outputs",
        ["user_id", "kind", "business_date", "monitor_id"],
        unique=True,
        sqlite_where=sa.text("monitor_id IS NOT NULL"),
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
    op.drop_index("idx_llm_task_attempts_agent_model_time", table_name="llm_task_attempts")
    op.drop_index("idx_llm_task_attempts_failure_time", table_name="llm_task_attempts")
    op.drop_index("idx_llm_task_attempts_task_type_time", table_name="llm_task_attempts")
    op.drop_index("idx_llm_task_attempts_scope_time", table_name="llm_task_attempts")
    op.drop_index("uq_user_outputs_monitor_answer", table_name="user_outputs")
    op.drop_index("uq_user_outputs_story_detail", table_name="user_outputs")
    op.drop_index("uq_user_outputs_daily_highlights", table_name="user_outputs")
    op.drop_index("idx_output_feedback_scope_time", table_name="output_feedback")
    op.drop_index("idx_read_state_events_scope_time", table_name="read_state_events")
    op.drop_index("idx_user_output_blocks_scope_output", table_name="user_output_blocks")
    op.drop_index("idx_story_assignments_scope_story", table_name="story_assignments")
    op.drop_index(
        "idx_output_citation_snapshots_scope_task",
        table_name="output_citation_snapshots",
    )
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
    op.drop_table("output_feedback")
    op.drop_table("read_state_events")
    op.drop_table("user_output_blocks")
    op.drop_table("user_outputs")
    op.drop_table("monitor_questions")
    op.drop_table("daily_story_snapshots")
    op.drop_table("story_assignments")
    op.drop_table("user_story_definitions")
    op.drop_table("llm_task_artifacts")
    op.drop_table("llm_task_events")
    op.drop_table("output_citation_snapshots")
    op.drop_table("llm_task_attempts")
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
