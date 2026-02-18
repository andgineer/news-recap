"""SQLModel ORM tables for ingestion storage."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
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
