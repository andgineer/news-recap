"""Domain models for ingestion and storage stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import msgspec


class RunStatus(StrEnum):
    """Lifecycle states for ingestion runs."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    PARTIAL = "partial"


class GapStatus(StrEnum):
    """Lifecycle states for ingestion gaps."""

    OPEN = "open"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class UpsertAction(StrEnum):
    """Operation result for article upsert."""

    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED = "skipped"


class SourceArticle(msgspec.Struct):
    """Normalized article payload from a source connector."""

    external_id: str
    url: str
    title: str
    source: str
    published_at: datetime
    content: str | None = None
    summary: str | None = None
    raw_payload: dict[str, object] = {}


class SourcePage(msgspec.Struct):
    """Page of source articles with cursor-based pagination."""

    articles: list[SourceArticle]
    next_cursor: str | None
    cursor: str | None


class NormalizedArticle(msgspec.Struct):
    """Article record ready for persistence."""

    source_name: str
    external_id: str
    url: str
    url_canonical: str
    url_hash: str
    title: str
    source_domain: str
    published_at: datetime
    language_detected: str
    content_raw: str | None
    summary_raw: str | None
    is_full_content: bool
    needs_enrichment: bool
    clean_text: str
    clean_text_chars: int
    is_truncated: bool


class UpsertResult(msgspec.Struct):
    """Result of persisting a normalized article."""

    article_id: str
    action: UpsertAction


class IngestionGap(msgspec.Struct):
    """Failed ingestion window that should be retried."""

    gap_id: int
    source: str
    from_cursor_or_time: str | None
    to_cursor_or_time: str | None
    error_code: str
    retry_after: int | None
    status: GapStatus


class GapWrite(msgspec.Struct):
    """Input payload for recording failed source windows."""

    from_cursor_or_time: str | None
    to_cursor_or_time: str | None
    error_code: str
    retry_after: int | None


@dataclass(slots=True)
class IngestionRunCounters:
    """Counters tracked for ingestion run statistics — mutable, stays dataclass."""

    ingested_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    gaps_opened_count: int = 0


class IngestionWindowStats(msgspec.Struct):
    """Aggregated ingestion counters for a time window."""

    runs_count: int = 0
    succeeded_runs_count: int = 0
    partial_runs_count: int = 0
    failed_runs_count: int = 0
    other_runs_count: int = 0
    ingested_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    gaps_opened_count: int = 0


class IngestionRunView(msgspec.Struct):
    """Compact run view for CLI reporting."""

    run_id: str
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    ingested_count: int
    updated_count: int
    skipped_count: int
    gaps_opened_count: int


# ---------------------------------------------------------------------------
# Persisted domain structs (replace SQLModel tables)
# ---------------------------------------------------------------------------


class Article(msgspec.Struct):
    """Persisted article — replaces both Article SQLModel + NormalizedArticle dataclass."""

    article_id: str
    source_name: str
    external_id: str
    url: str
    url_canonical: str
    url_hash: str
    title: str
    source_domain: str
    published_at: datetime
    language_detected: str
    clean_text: str
    clean_text_chars: int
    is_full_content: bool
    is_truncated: bool
    ingested_at: datetime
    content_raw: str | None = None
    summary_raw: str | None = None
    fallback_key: str | None = None
    raw_json: str | None = None


class DailyStore(msgspec.Struct):
    """One calendar day of articles."""

    articles: dict[str, Article] = {}
    embeddings: dict[str, list[float]] = {}


class FeedState(msgspec.Struct):
    """HTTP cache validators for one RSS feed."""

    source_name: str
    feed_url: str
    etag: str | None = None
    last_modified: str | None = None
    updated_at: datetime | None = None


class ProcessingSnapshot(msgspec.Struct):
    """Crash-safe RSS processing snapshot."""

    source_name: str
    feed_set_hash: str
    snapshot_json: str
    next_cursor: str | None = None
    updated_at: datetime | None = None


class FeedsStore(msgspec.Struct):
    """Persisted RSS feed states and processing snapshots."""

    feed_states: dict[str, FeedState] = {}
    processing_snapshots: dict[str, ProcessingSnapshot] = {}


class IngestionRunRecord(msgspec.Struct):
    """Persisted ingestion run record for CLI observability."""

    run_id: str
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    ingested_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    dedup_clusters_count: int = 0
    dedup_duplicates_count: int = 0
    gaps_opened_count: int = 0
    error_summary: str | None = None


class RunsStore(msgspec.Struct):
    """Persisted recent ingestion runs."""

    runs: list[IngestionRunRecord] = []
    gaps: list[IngestionGap] = []
    dedup_results: dict[str, Any] = {}
