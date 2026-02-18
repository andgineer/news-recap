"""Domain models for ingestion, storage, and dedup stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RunStatus(str, Enum):
    """Lifecycle states for ingestion runs."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    PARTIAL = "partial"


class GapStatus(str, Enum):
    """Lifecycle states for ingestion gaps."""

    OPEN = "open"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class UpsertAction(str, Enum):
    """Operation result for article upsert."""

    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED = "skipped"


@dataclass(slots=True)
class SourceArticle:
    """Normalized article payload from a source connector."""

    external_id: str
    url: str
    title: str
    source: str
    published_at: datetime
    content: str | None = None
    summary: str | None = None
    raw_payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SourcePage:
    """Page of source articles with cursor-based pagination."""

    articles: list[SourceArticle]
    next_cursor: str | None
    cursor: str | None


@dataclass(slots=True)
class NormalizedArticle:
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


@dataclass(slots=True)
class UpsertResult:
    """Result of persisting a normalized article."""

    article_id: str
    action: UpsertAction


@dataclass(slots=True)
class IngestionGap:
    """Failed ingestion window that should be retried."""

    gap_id: int
    source: str
    from_cursor_or_time: str | None
    to_cursor_or_time: str | None
    error_code: str
    retry_after: int | None
    status: GapStatus


@dataclass(slots=True)
class GapWrite:
    """Input payload for recording failed source windows."""

    from_cursor_or_time: str | None
    to_cursor_or_time: str | None
    error_code: str
    retry_after: int | None


@dataclass(slots=True)
class IngestionRunCounters:
    """Counters tracked for ingestion run statistics."""

    ingested_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    dedup_clusters_count: int = 0
    dedup_duplicates_count: int = 0
    gaps_opened_count: int = 0


@dataclass(slots=True)
class IngestionWindowStats:
    """Aggregated ingestion counters for a time window."""

    runs_count: int = 0
    succeeded_runs_count: int = 0
    partial_runs_count: int = 0
    failed_runs_count: int = 0
    other_runs_count: int = 0
    ingested_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    dedup_clusters_count: int = 0
    dedup_duplicates_count: int = 0
    gaps_opened_count: int = 0


@dataclass(slots=True)
class IngestionRunView:
    """Compact run view for CLI reporting."""

    run_id: str
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    ingested_count: int
    updated_count: int
    skipped_count: int
    dedup_clusters_count: int
    dedup_duplicates_count: int
    gaps_opened_count: int


@dataclass(slots=True)
class DedupCandidate:
    """Article view used by deduplication stage."""

    article_id: str
    title: str
    url: str
    source_domain: str
    published_at: datetime
    clean_text: str
    clean_text_chars: int


@dataclass(slots=True)
class ClusterMember:
    """Dedup cluster member metadata."""

    article_id: str
    similarity_to_representative: float
    is_representative: bool


@dataclass(slots=True)
class DedupCluster:
    """Dedup cluster with representative and alternative sources."""

    cluster_id: str
    representative_article_id: str
    alt_sources: list[dict[str, str]]
    members: list[ClusterMember]


@dataclass(slots=True)
class ClusterMemberPreview:
    """Readable article entry for cluster inspection."""

    article_id: str
    title: str
    url: str
    source_domain: str
    similarity_to_representative: float
    is_representative: bool


@dataclass(slots=True)
class ClusterPreview:
    """Cluster details for observability commands."""

    cluster_id: str
    run_id: str
    size: int
    representative_article_id: str
    representative_title: str
    representative_url: str
    members: list[ClusterMemberPreview] = field(default_factory=list)


@dataclass(slots=True)
class ClusterListResult:
    """Paginated view of clusters for one ingestion run."""

    run_id: str
    total_clusters: int
    total_articles: int
    clusters: list[ClusterPreview]


@dataclass(slots=True)
class RetentionPruneResult:
    """Result of retention cleanup for article-related records."""

    cutoff: datetime
    dry_run: bool
    articles_deleted: int
    raw_payloads_deleted: int
    private_resources_deleted: int = 0


@dataclass(slots=True)
class GlobalGcResult:
    """Result of global garbage collection for unreferenced shared records."""

    dry_run: bool
    articles_deleted: int
    raw_payloads_deleted: int
    public_resources_deleted: int
