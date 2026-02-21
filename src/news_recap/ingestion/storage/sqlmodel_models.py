"""SQLModel ORM tables for ingestion storage."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel

DEFAULT_USER_ID = "default_user"


class AppUser(SQLModel, table=True):
    __tablename__ = "users"  # type: ignore[bad-override]

    user_id: str = Field(primary_key=True, index=True)
    display_name: str = Field(index=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class IngestionRun(SQLModel, table=True):
    __tablename__ = "ingestion_runs"  # type: ignore[bad-override]
    __table_args__ = (
        Index(
            "uq_ingestion_runs_scope_source_running",
            "user_id",
            "source",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    run_id: str = Field(primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    source: str = Field(index=True)
    status: str = Field(index=True)
    started_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    heartbeat_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    ingested_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    dedup_clusters_count: int = 0
    dedup_duplicates_count: int = 0
    gaps_opened_count: int = 0
    error_summary: str | None = None


class IngestionGap(SQLModel, table=True):
    __tablename__ = "ingestion_gaps"  # type: ignore[bad-override]

    gap_id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    run_id: str = Field(foreign_key="ingestion_runs.run_id", index=True)
    source: str = Field(index=True)
    from_cursor_or_time: str | None = None
    to_cursor_or_time: str | None = None
    error_code: str
    retry_after: int | None = None
    status: str = Field(index=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    resolved_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class RssFeedState(SQLModel, table=True):
    __tablename__ = "rss_feed_states"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_name",
            "feed_url",
            name="uq_rss_feed_states_scope_source_url",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    source_name: str = Field(index=True)
    feed_url: str = Field(index=True)
    etag: str | None = None
    last_modified: str | None = None
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class RssProcessingSnapshot(SQLModel, table=True):
    __tablename__ = "rss_processing_snapshots"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_name",
            "feed_set_hash",
            name="uq_rss_processing_snapshots_scope_source_feed_set",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    source_name: str = Field(index=True)
    feed_set_hash: str = Field(index=True)
    snapshot_json: str = Field(sa_column=Column(Text, nullable=False))
    next_cursor: str | None = None
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class Article(SQLModel, table=True):
    __tablename__ = "articles"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_articles_source_external",
        ),
    )

    article_id: str = Field(primary_key=True)
    source_name: str = Field(index=True)
    external_id: str = Field(index=True)
    url: str
    url_canonical: str
    url_hash: str = Field(index=True)
    title: str
    source_domain: str = Field(index=True)
    published_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), index=True, nullable=False),
    )
    language_detected: str = Field(index=True)
    content_raw: str | None = Field(default=None, sa_column=Column(Text))
    summary_raw: str | None = Field(default=None, sa_column=Column(Text))
    is_full_content: bool
    clean_text: str = Field(sa_column=Column(Text, nullable=False))
    clean_text_chars: int
    is_truncated: bool
    ingested_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    fallback_key: str | None = Field(default=None, index=True)
    last_processed_run_id: str


class UserArticle(SQLModel, table=True):
    __tablename__ = "user_articles"  # type: ignore[bad-override]
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "article_id", name="pk_user_articles"),
        Index("idx_user_articles_user_discovered", "user_id", "discovered_at"),
    )

    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    article_id: str = Field(
        sa_column=Column(
            ForeignKey("articles.article_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    discovered_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    state: str = Field(default="active", index=True)
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class ArticleExternalId(SQLModel, table=True):
    __tablename__ = "article_external_ids"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_article_external_ids_source_external",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    source_name: str = Field(index=True)
    external_id: str = Field(index=True)
    article_id: str = Field(foreign_key="articles.article_id", index=True)
    is_primary: bool = False
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class ArticleRaw(SQLModel, table=True):
    __tablename__ = "articles_raw"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "external_id",
            name="uq_articles_raw_source_external",
        ),
        UniqueConstraint(
            "article_id",
            name="uq_articles_raw_article",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    article_id: str = Field(foreign_key="articles.article_id", index=True)
    source_name: str = Field(index=True)
    external_id: str = Field(index=True)
    raw_json: str = Field(sa_column=Column(Text, nullable=False))
    first_seen_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class ArticleEmbedding(SQLModel, table=True):
    __tablename__ = "article_embeddings"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "model_name",
            name="uq_article_embeddings_article_model",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    article_id: str = Field(foreign_key="articles.article_id", index=True)
    model_name: str = Field(index=True)
    embedding_dim: int
    embedding_blob: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=True),
    )


class ArticleResource(SQLModel, table=True):
    __tablename__ = "article_resources"  # type: ignore[bad-override]
    __table_args__ = (
        Index(
            "uq_article_resources_public_url_hash",
            "url_hash",
            unique=True,
            sqlite_where=text("user_id IS NULL"),
        ),
        Index(
            "uq_article_resources_private_user_url_hash",
            "user_id",
            "url_hash",
            unique=True,
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index("idx_article_resources_lookup", "url_hash", "user_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True),
    )
    url_hash: str = Field(index=True)
    url_canonical: str
    fetch_status: str = Field(index=True)
    http_status: int | None = None
    content_text: str | None = Field(default=None, sa_column=Column(Text))
    error_code: str | None = Field(default=None, index=True)
    fetched_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), index=True),
    )


class DedupCluster(SQLModel, table=True):
    __tablename__ = "dedup_clusters"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "run_id",
            "cluster_id",
            name="uq_dedup_clusters_scope_run_cluster",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    run_id: str = Field(foreign_key="ingestion_runs.run_id", index=True)
    cluster_id: str = Field(index=True)
    representative_article_id: str = Field(foreign_key="articles.article_id", index=True)
    alt_sources_json: str = Field(sa_column=Column(Text, nullable=False))
    model_name: str = Field(index=True)
    threshold: float
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class ArticleDedup(SQLModel, table=True):
    __tablename__ = "article_dedup"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "run_id",
            "article_id",
            name="uq_article_dedup_scope_run_article",
        ),
        ForeignKeyConstraint(
            ["user_id", "run_id", "cluster_id"],
            ["dedup_clusters.user_id", "dedup_clusters.run_id", "dedup_clusters.cluster_id"],
            ondelete="CASCADE",
            name="fk_article_dedup_cluster_scope",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    run_id: str = Field(index=True)
    article_id: str = Field(foreign_key="articles.article_id", index=True)
    cluster_id: str = Field(index=True)
    is_representative: bool
    similarity_to_rep: float


class LlmTask(SQLModel, table=True):
    __tablename__ = "llm_tasks"  # type: ignore[bad-override]
    __table_args__ = (Index("idx_llm_tasks_queue", "user_id", "status", "priority", "run_after"),)

    task_id: str = Field(primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    task_type: str = Field(index=True)
    priority: int = Field(default=100, index=True)
    status: str = Field(index=True)
    attempt: int = Field(default=0)
    max_attempts: int = Field(default=3)
    timeout_seconds: int = Field(default=600)
    run_after: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    heartbeat_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    failure_class: str | None = Field(default=None, index=True)
    last_exit_code: int | None = None
    repair_attempted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    worker_id: str | None = Field(default=None, index=True)
    input_manifest_path: str
    output_path: str | None = None
    error_summary: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class LlmTaskAttempt(SQLModel, table=True):
    __tablename__ = "llm_task_attempts"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt_no",
            name="uq_llm_task_attempts_task_attempt_no",
        ),
        Index("idx_llm_task_attempts_scope_time", "user_id", "created_at"),
        Index("idx_llm_task_attempts_task_type_time", "task_type", "created_at"),
        Index("idx_llm_task_attempts_failure_time", "failure_class", "created_at"),
        Index("idx_llm_task_attempts_agent_model_time", "agent", "model", "created_at"),
    )

    attempt_id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(
        sa_column=Column(
            ForeignKey("llm_tasks.task_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    attempt_no: int = Field(index=True)
    task_type: str = Field(index=True)
    status: str = Field(index=True)
    started_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    duration_ms: int | None = None
    worker_id: str | None = Field(default=None, index=True)
    agent: str | None = Field(default=None, index=True)
    model: str | None = Field(default=None, index=True)
    profile: str | None = Field(default=None, index=True)
    command_template_hash: str | None = None
    exit_code: int | None = None
    timed_out: bool = Field(default=False)
    failure_class: str | None = Field(default=None, index=True)
    attempt_failure_code: str | None = Field(default=None, index=True)
    error_summary_sanitized: str | None = Field(default=None, sa_column=Column(Text))
    stdout_preview_sanitized: str | None = Field(default=None, sa_column=Column(Text))
    stderr_preview_sanitized: str | None = Field(default=None, sa_column=Column(Text))
    output_chars: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    usage_status: str | None = Field(default=None, index=True)
    usage_source: str | None = Field(default=None)
    usage_parser_version: str | None = Field(default=None)
    estimated_cost_usd: float | None = None
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class LlmTaskEvent(SQLModel, table=True):
    __tablename__ = "llm_task_events"  # type: ignore[bad-override]
    __table_args__ = (Index("idx_llm_task_events_task_time", "task_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(
        sa_column=Column(
            ForeignKey("llm_tasks.task_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    event_type: str = Field(index=True)
    status_from: str | None = Field(default=None, index=True)
    status_to: str | None = Field(default=None, index=True)
    details_json: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class LlmTaskArtifact(SQLModel, table=True):
    __tablename__ = "llm_task_artifacts"  # type: ignore[bad-override]
    __table_args__ = (Index("idx_llm_task_artifacts_task_kind", "task_id", "kind"),)

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(
        sa_column=Column(
            ForeignKey("llm_tasks.task_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    kind: str = Field(index=True)
    path: str
    size_bytes: int
    checksum_sha256: str | None = None
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class OutputCitationSnapshot(SQLModel, table=True):
    __tablename__ = "output_citation_snapshots"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "task_id",
            "source_id",
            name="uq_output_citation_snapshots_scope_task_source",
        ),
        Index(
            "idx_output_citation_snapshots_scope_task",
            "user_id",
            "task_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    task_id: str = Field(
        sa_column=Column(
            ForeignKey("llm_tasks.task_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    source_id: str = Field(index=True)
    article_id: str | None = Field(default=None, index=True)
    title: str
    url: str
    source: str = ""
    published_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class UserStoryDefinition(SQLModel, table=True):
    __tablename__ = "user_story_definitions"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            name="uq_user_story_definitions_scope_name",
        ),
        UniqueConstraint(
            "user_id",
            "story_id",
            name="uq_user_story_definitions_scope_story",
        ),
    )

    story_id: str = Field(primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    name: str = Field(index=True)
    target_language: str = Field(default="en", index=True)
    description: str = Field(sa_column=Column(Text, nullable=False))
    priority: int = Field(default=100, index=True)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class StoryAssignment(SQLModel, table=True):
    __tablename__ = "story_assignments"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "business_date",
            "article_id",
            name="uq_story_assignments_scope_date_article",
        ),
        ForeignKeyConstraint(
            ["user_id", "story_id"],
            ["user_story_definitions.user_id", "user_story_definitions.story_id"],
            ondelete="SET NULL",
            name="fk_story_assignments_story_scope",
        ),
        Index("idx_story_assignments_scope_story", "user_id", "business_date", "story_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    business_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    article_id: str = Field(
        sa_column=Column(
            ForeignKey("articles.article_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    story_id: str | None = Field(default=None, index=True)
    story_key: str = Field(index=True)
    assignment_type: str = Field(index=True)
    score: float = 0.0
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class DailyStorySnapshot(SQLModel, table=True):
    __tablename__ = "daily_story_snapshots"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "business_date",
            "story_key",
            name="uq_daily_story_snapshots_scope_date_key",
        ),
        ForeignKeyConstraint(
            ["user_id", "story_id"],
            ["user_story_definitions.user_id", "user_story_definitions.story_id"],
            ondelete="SET NULL",
            name="fk_daily_story_snapshots_story_scope",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    business_date: date = Field(sa_column=Column(Date, nullable=False, index=True))
    story_id: str | None = Field(default=None, index=True)
    story_key: str = Field(index=True)
    title: str
    continuity_key: str | None = Field(default=None, index=True)
    summary_json: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class MonitorQuestion(SQLModel, table=True):
    __tablename__ = "monitor_questions"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "monitor_id",
            name="uq_monitor_questions_scope_monitor",
        ),
    )

    monitor_id: str = Field(primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    name: str = Field(index=True)
    prompt: str = Field(sa_column=Column(Text, nullable=False))
    cadence: str = Field(default="daily", index=True)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class UserOutput(SQLModel, table=True):
    __tablename__ = "user_outputs"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "output_id",
            name="uq_user_outputs_scope_output",
        ),
        UniqueConstraint(
            "user_id",
            "kind",
            "request_id",
            name="uq_user_outputs_scope_kind_request",
        ),
        Index(
            "uq_user_outputs_daily_highlights",
            "user_id",
            "kind",
            "business_date",
            unique=True,
            sqlite_where=text(
                "kind = 'highlights' "
                "AND story_id IS NULL "
                "AND monitor_id IS NULL "
                "AND request_id IS NULL",
            ),
        ),
        Index(
            "uq_user_outputs_story_detail",
            "user_id",
            "kind",
            "business_date",
            "story_id",
            unique=True,
            sqlite_where=text("story_id IS NOT NULL"),
        ),
        Index(
            "uq_user_outputs_monitor_answer",
            "user_id",
            "kind",
            "business_date",
            "monitor_id",
            unique=True,
            sqlite_where=text("monitor_id IS NOT NULL"),
        ),
    )

    output_id: str = Field(primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    kind: str = Field(index=True)
    business_date: date = Field(
        default_factory=lambda: datetime.now(tz=UTC).date(),
        sa_column=Column(Date, nullable=False, index=True),
    )
    story_id: str | None = Field(default=None, index=True)
    monitor_id: str | None = Field(default=None, index=True)
    request_id: str | None = Field(default=None, index=True)
    task_id: str | None = Field(
        default=None,
        sa_column=Column(ForeignKey("llm_tasks.task_id", ondelete="SET NULL"), nullable=True),
    )
    status: str = Field(index=True)
    title: str | None = None
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class UserOutputBlock(SQLModel, table=True):
    __tablename__ = "user_output_blocks"  # type: ignore[bad-override]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "block_id",
            name="uq_user_output_blocks_scope_block",
        ),
        UniqueConstraint(
            "user_id",
            "output_id",
            "block_id",
            name="uq_user_output_blocks_scope_output_block",
        ),
        UniqueConstraint(
            "user_id",
            "output_id",
            "block_order",
            name="uq_user_output_blocks_scope_order",
        ),
        ForeignKeyConstraint(
            ["user_id", "output_id"],
            ["user_outputs.user_id", "user_outputs.output_id"],
            ondelete="CASCADE",
            name="fk_user_output_blocks_output_scope",
        ),
        Index("idx_user_output_blocks_scope_output", "user_id", "output_id"),
    )

    block_id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    output_id: str = Field(index=True)
    block_order: int = Field(index=True)
    text: str = Field(sa_column=Column(Text, nullable=False))
    source_ids_json: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class ReadStateEvent(SQLModel, table=True):
    __tablename__ = "read_state_events"  # type: ignore[bad-override]
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "output_id"],
            ["user_outputs.user_id", "user_outputs.output_id"],
            ondelete="CASCADE",
            name="fk_read_state_events_output_scope",
        ),
        ForeignKeyConstraint(
            ["user_id", "output_block_id"],
            ["user_output_blocks.user_id", "user_output_blocks.block_id"],
            ondelete="CASCADE",
            name="fk_read_state_events_block_scope",
        ),
        ForeignKeyConstraint(
            ["user_id", "output_id", "output_block_id"],
            [
                "user_output_blocks.user_id",
                "user_output_blocks.output_id",
                "user_output_blocks.block_id",
            ],
            ondelete="CASCADE",
            name="fk_read_state_events_output_block_scope",
        ),
        Index("idx_read_state_events_scope_time", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    output_id: str = Field(index=True)
    output_block_id: int | None = Field(default=None, index=True)
    event_type: str = Field(index=True)
    details_json: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class OutputFeedback(SQLModel, table=True):
    __tablename__ = "output_feedback"  # type: ignore[bad-override]
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "output_id"],
            ["user_outputs.user_id", "user_outputs.output_id"],
            ondelete="CASCADE",
            name="fk_output_feedback_output_scope",
        ),
        ForeignKeyConstraint(
            ["user_id", "output_block_id"],
            ["user_output_blocks.user_id", "user_output_blocks.block_id"],
            ondelete="CASCADE",
            name="fk_output_feedback_block_scope",
        ),
        ForeignKeyConstraint(
            ["user_id", "output_id", "output_block_id"],
            [
                "user_output_blocks.user_id",
                "user_output_blocks.output_id",
                "user_output_blocks.block_id",
            ],
            ondelete="CASCADE",
            name="fk_output_feedback_output_block_scope",
        ),
        Index("idx_output_feedback_scope_time", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    output_id: str = Field(index=True)
    output_block_id: int | None = Field(default=None, index=True)
    feedback_type: str = Field(index=True)
    value: str | None = None
    details_json: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class RecapPipelineRun(SQLModel, table=True):
    __tablename__ = "recap_pipeline_runs"  # type: ignore[bad-override]
    __table_args__ = (Index("idx_recap_pipeline_runs_user_date", "user_id", "business_date"),)

    pipeline_id: str = Field(primary_key=True)
    user_id: str = Field(
        default=DEFAULT_USER_ID,
        sa_column=Column(
            ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            server_default=DEFAULT_USER_ID,
            index=True,
        ),
    )
    business_date: date = Field(sa_column=Column(Date, nullable=False))
    status: str = Field(default="running", index=True)
    current_step: str | None = None
    error: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class RecapPipelineTask(SQLModel, table=True):
    __tablename__ = "recap_pipeline_tasks"  # type: ignore[bad-override]
    __table_args__ = (Index("idx_recap_pipeline_tasks_pipeline", "pipeline_id"),)

    id: int | None = Field(default=None, primary_key=True)
    pipeline_id: str = Field(
        sa_column=Column(
            ForeignKey("recap_pipeline_runs.pipeline_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    step_name: str = Field(index=True)
    task_id: str | None = Field(default=None, index=True)
    status: str = Field(default="pending")
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
