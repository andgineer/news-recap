"""File-based ingestion store with daily-partitioned article storage."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from news_recap.ingestion.models import (
    Article,
    DailyStore,
    FeedsStore,
    FeedState,
    GapStatus,
    GapWrite,
    IngestionGap,
    IngestionRunCounters,
    IngestionRunRecord,
    IngestionRunView,
    IngestionWindowStats,
    NormalizedArticle,
    ProcessingSnapshot,
    RunsStore,
    RunStatus,
    UpsertAction,
    UpsertResult,
)
from news_recap.recap.models import DigestArticle
from news_recap.storage.io import (
    day_key,
    gc_old_days,
    load_msgspec,
    save_msgspec,
    utc_now,
)

logger = logging.getLogger(__name__)


class IngestionStore:
    """File-based storage facade for the ingestion pipeline.

    Articles are stored in daily partition files (``articles-YYYY-MM-DD.json``).
    Feed states and runs are stored in separate JSON files.
    """

    def __init__(self, data_dir: Path, *, gc_retention_days: int = 7) -> None:
        self.data_dir = data_dir
        self._gc_retention_days = gc_retention_days
        self._ingestion_dir = data_dir / "ingestion"
        self._ingestion_dir.mkdir(parents=True, exist_ok=True)

        self._feeds_path = self._ingestion_dir / "feeds.json"
        self._runs_path = self._ingestion_dir / "runs.json"

        self._daily_cache: dict[str, DailyStore] = {}
        self._feeds: FeedsStore | None = None
        self._runs: RunsStore | None = None

    def close(self) -> None:
        """Flush any cached state (no-op in file-based store)."""

    def init_schema(self) -> None:
        """Ensure data directories exist and run automatic GC."""
        self._ingestion_dir.mkdir(parents=True, exist_ok=True)
        deleted = gc_old_days(self.data_dir, keep_days=self._gc_retention_days)
        if deleted:
            logger.info("Auto-GC: deleted %d old daily partition(s).", len(deleted))
        self._gc_old_runs()

    # ------------------------------------------------------------------
    # Daily article storage
    # ------------------------------------------------------------------

    def _day_path(self, dk: str) -> Path:
        return self._ingestion_dir / f"articles-{dk}.json"

    def _load_day(self, dk: str) -> DailyStore:
        if dk in self._daily_cache:
            return self._daily_cache[dk]
        path = self._day_path(dk)
        store = load_msgspec(path, DailyStore) if path.exists() else DailyStore()
        self._daily_cache[dk] = store
        return store

    def _save_day(self, dk: str) -> None:
        store = self._daily_cache.get(dk)
        if store is None:
            return
        save_msgspec(self._day_path(dk), store)

    def _load_recent_days(self, n: int | None = None) -> dict[str, DailyStore]:
        """Load up to *n* most recent daily stores (defaults to gc_retention_days)."""
        if n is None:
            n = self._gc_retention_days
        today = date.today()
        keys = [(today - timedelta(days=i)).isoformat() for i in range(n)]
        return {k: self._load_day(k) for k in keys}

    def _all_articles(self, days: dict[str, DailyStore] | None = None) -> dict[str, Article]:
        """Return all articles across loaded days."""
        if days is None:
            days = self._load_recent_days()
        merged: dict[str, Article] = {}
        for store in days.values():
            merged.update(store.articles)
        return merged

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def _load_runs(self) -> RunsStore:
        if self._runs is not None:
            return self._runs
        runs = load_msgspec(self._runs_path, RunsStore) if self._runs_path.exists() else RunsStore()
        self._runs = runs
        return runs

    def _save_runs(self) -> None:
        if self._runs is not None:
            save_msgspec(self._runs_path, self._runs)

    def _gc_old_runs(self) -> None:
        """Drop old run records and recover stale running runs.

        Uses ``gc_retention_days`` as the single retention threshold for everything.
        """
        runs_store = self._load_runs()
        cutoff = utc_now() - timedelta(days=self._gc_retention_days)
        dirty = False

        for run in runs_store.runs:
            if run.status == RunStatus.RUNNING.value and run.started_at < cutoff:
                run.status = RunStatus.FAILED.value
                run.finished_at = cutoff
                run.error_summary = "Auto-recovered stale running run after crash/interruption."
                logger.warning(
                    "Recovered stale running ingestion run (run_id=%s).",
                    run.run_id,
                )
                dirty = True

        before = len(runs_store.runs)
        runs_store.runs = [r for r in runs_store.runs if r.started_at >= cutoff]
        if len(runs_store.runs) < before or dirty:
            self._save_runs()

    def start_run(self, source: str) -> str:
        runs_store = self._load_runs()
        now = utc_now()

        for run in runs_store.runs:
            if run.source == source and run.status == RunStatus.RUNNING.value:
                raise RuntimeError(
                    "Another ingestion run is already active for this source "
                    f"(source={source}, run_id={run.run_id}, "
                    f"started_at={run.started_at.isoformat()}).",
                )

        run_id = str(uuid4())
        runs_store.runs.insert(
            0,
            IngestionRunRecord(
                run_id=run_id,
                source=source,
                status=RunStatus.RUNNING.value,
                started_at=now,
                heartbeat_at=now,
            ),
        )
        self._save_runs()
        return run_id

    def touch_run(self, run_id: str) -> None:
        runs_store = self._load_runs()
        for run in runs_store.runs:
            if run.run_id == run_id and run.status == RunStatus.RUNNING.value:
                run.heartbeat_at = utc_now()
                self._save_runs()
                return

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        counters: IngestionRunCounters,
        error_summary: str | None = None,
    ) -> None:
        runs_store = self._load_runs()
        now = utc_now()
        for run in runs_store.runs:
            if run.run_id == run_id:
                run.status = status.value
                run.finished_at = now
                run.heartbeat_at = now
                run.ingested_count = counters.ingested_count
                run.updated_count = counters.updated_count
                run.skipped_count = counters.skipped_count
                run.gaps_opened_count = counters.gaps_opened_count
                run.error_summary = error_summary
                break
        else:
            raise RuntimeError(f"Run not found: {run_id}")
        self._save_runs()

    def summarize_runs(
        self,
        *,
        since: datetime,
        until: datetime,
        source: str | None = None,
    ) -> IngestionWindowStats:
        runs_store = self._load_runs()
        stats = IngestionWindowStats()
        for run in runs_store.runs:
            if run.started_at < since or run.started_at >= until:
                continue
            if source is not None and run.source != source:
                continue
            stats.runs_count += 1
            stats.ingested_count += run.ingested_count
            stats.updated_count += run.updated_count
            stats.skipped_count += run.skipped_count
            stats.gaps_opened_count += run.gaps_opened_count
            if run.status == RunStatus.SUCCEEDED.value:
                stats.succeeded_runs_count += 1
            elif run.status == RunStatus.PARTIAL.value:
                stats.partial_runs_count += 1
            elif run.status == RunStatus.FAILED.value:
                stats.failed_runs_count += 1
            else:
                stats.other_runs_count += 1
        return stats

    def list_recent_runs(
        self,
        *,
        limit: int = 5,
        source: str | None = None,
    ) -> list[IngestionRunView]:
        runs_store = self._load_runs()
        result: list[IngestionRunView] = []
        for run in runs_store.runs:
            if source is not None and run.source != source:
                continue
            result.append(
                IngestionRunView(
                    run_id=run.run_id,
                    source=run.source,
                    status=run.status,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    ingested_count=run.ingested_count,
                    updated_count=run.updated_count,
                    skipped_count=run.skipped_count,
                    gaps_opened_count=run.gaps_opened_count,
                ),
            )
            if len(result) >= limit:
                break
        return result

    # ------------------------------------------------------------------
    # Article upsert
    # ------------------------------------------------------------------

    def upsert_article(self, article: NormalizedArticle, run_id: str) -> UpsertResult:
        dk = day_key(article.published_at)
        store = self._load_day(dk)

        existing_id = self._find_existing_article_id(store, article)
        if existing_id is not None:
            existing = store.articles[existing_id]
            if _article_changed(existing, article):
                store.articles[existing_id] = _update_article(existing, article, run_id)
                self._save_day(dk)
                return UpsertResult(article_id=existing_id, action=UpsertAction.UPDATED)
            return UpsertResult(article_id=existing_id, action=UpsertAction.SKIPPED)

        article_id = str(uuid4())
        now = utc_now()
        store.articles[article_id] = Article(
            article_id=article_id,
            source_name=article.source_name,
            external_id=article.external_id,
            url=article.url,
            url_canonical=article.url_canonical,
            url_hash=article.url_hash,
            title=article.title,
            source_domain=article.source_domain,
            published_at=article.published_at,
            language_detected=article.language_detected,
            clean_text=article.clean_text,
            clean_text_chars=article.clean_text_chars,
            is_full_content=article.is_full_content,
            is_truncated=article.is_truncated,
            ingested_at=now,
            content_raw=article.content_raw,
            summary_raw=article.summary_raw,
        )
        self._save_day(dk)
        return UpsertResult(article_id=article_id, action=UpsertAction.INSERTED)

    def upsert_raw_article(
        self,
        source_name: str,  # noqa: ARG002
        external_id: str,  # noqa: ARG002
        raw_payload: dict[str, object],
        *,
        article_id: str | None = None,
    ) -> None:
        """Store raw JSON payload inline in the article."""
        if article_id is None:
            return
        raw_json = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        days = self._load_recent_days()
        for dk, store in days.items():
            if article_id in store.articles:
                art = store.articles[article_id]
                if art.raw_json != raw_json:
                    store.articles[article_id] = Article(
                        article_id=art.article_id,
                        source_name=art.source_name,
                        external_id=art.external_id,
                        url=art.url,
                        url_canonical=art.url_canonical,
                        url_hash=art.url_hash,
                        title=art.title,
                        source_domain=art.source_domain,
                        published_at=art.published_at,
                        language_detected=art.language_detected,
                        clean_text=art.clean_text,
                        clean_text_chars=art.clean_text_chars,
                        is_full_content=art.is_full_content,
                        is_truncated=art.is_truncated,
                        ingested_at=art.ingested_at,
                        content_raw=art.content_raw,
                        summary_raw=art.summary_raw,
                        fallback_key=art.fallback_key,
                        raw_json=raw_json,
                    )
                    self._save_day(dk)
                return

    def _find_existing_article_id(
        self,
        store: DailyStore,
        article: NormalizedArticle,
    ) -> str | None:
        for aid, existing in store.articles.items():
            if (
                existing.source_name == article.source_name
                and existing.external_id == article.external_id
            ):
                return aid
        for aid, existing in store.articles.items():
            if (
                existing.source_name == article.source_name
                and existing.url_canonical == article.url_canonical
            ):
                return aid
        return None

    # ------------------------------------------------------------------
    # Gaps
    # ------------------------------------------------------------------

    def create_gap(self, *, run_id: str, source: str, gap: GapWrite) -> int:  # noqa: ARG002
        runs_store = self._load_runs()
        gap_id = max((g.gap_id for g in runs_store.gaps), default=0) + 1
        runs_store.gaps.append(
            IngestionGap(
                gap_id=gap_id,
                source=source,
                from_cursor_or_time=gap.from_cursor_or_time,
                to_cursor_or_time=gap.to_cursor_or_time,
                error_code=gap.error_code,
                retry_after=gap.retry_after,
                status=GapStatus.OPEN,
            ),
        )
        self._save_runs()
        return gap_id

    def list_open_gaps(self, source: str, limit: int) -> list[IngestionGap]:
        runs_store = self._load_runs()
        result: list[IngestionGap] = []
        for gap in runs_store.gaps:
            if gap.source == source and gap.status == GapStatus.OPEN:
                result.append(gap)
                if len(result) >= limit:
                    break
        return result

    def resolve_gap(self, gap_id: int) -> None:
        runs_store = self._load_runs()
        for gap in runs_store.gaps:
            if gap.gap_id == gap_id:
                gap.status = GapStatus.RESOLVED
                self._save_runs()
                return

    # ------------------------------------------------------------------
    # Feed state (RSS HTTP cache + processing snapshots)
    # ------------------------------------------------------------------

    def _load_feeds(self) -> FeedsStore:
        if self._feeds is not None:
            return self._feeds
        feeds = (
            load_msgspec(self._feeds_path, FeedsStore)
            if self._feeds_path.exists()
            else FeedsStore()
        )
        self._feeds = feeds
        return feeds

    def _save_feeds(self) -> None:
        if self._feeds is not None:
            save_msgspec(self._feeds_path, self._feeds)

    def get_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
    ) -> tuple[str | None, str | None]:
        feeds = self._load_feeds()
        key = f"{source_name}::{feed_url}"
        state = feeds.feed_states.get(key)
        if state is None:
            return None, None
        return state.etag, state.last_modified

    def upsert_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        feeds = self._load_feeds()
        key = f"{source_name}::{feed_url}"
        feeds.feed_states[key] = FeedState(
            source_name=source_name,
            feed_url=feed_url,
            etag=etag,
            last_modified=last_modified,
            updated_at=utc_now(),
        )
        self._save_feeds()

    def get_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> tuple[str, str | None, datetime] | None:
        feeds = self._load_feeds()
        key = f"{source_name}::{feed_set_hash}"
        snap = feeds.processing_snapshots.get(key)
        if snap is None:
            return None
        return snap.snapshot_json, snap.next_cursor, snap.updated_at or utc_now()

    def upsert_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        snapshot_json: str,
        next_cursor: str | None,
    ) -> None:
        feeds = self._load_feeds()
        key = f"{source_name}::{feed_set_hash}"
        feeds.processing_snapshots[key] = ProcessingSnapshot(
            source_name=source_name,
            feed_set_hash=feed_set_hash,
            snapshot_json=snapshot_json,
            next_cursor=next_cursor,
            updated_at=utc_now(),
        )
        self._save_feeds()

    def update_rss_processing_snapshot_cursor(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        next_cursor: str | None,
    ) -> bool:
        feeds = self._load_feeds()
        key = f"{source_name}::{feed_set_hash}"
        snap = feeds.processing_snapshots.get(key)
        if snap is None:
            logger.warning(
                "RSS snapshot cursor update skipped (source=%s, hash=%s).",
                source_name,
                feed_set_hash,
            )
            return False
        feeds.processing_snapshots[key] = ProcessingSnapshot(
            source_name=snap.source_name,
            feed_set_hash=snap.feed_set_hash,
            snapshot_json=snap.snapshot_json,
            next_cursor=next_cursor,
            updated_at=utc_now(),
        )
        self._save_feeds()
        return True

    def delete_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> None:
        feeds = self._load_feeds()
        key = f"{source_name}::{feed_set_hash}"
        if key in feeds.processing_snapshots:
            del feeds.processing_snapshots[key]
            self._save_feeds()

    # ------------------------------------------------------------------
    # Retrieval for recap pipeline
    # ------------------------------------------------------------------

    def list_retrieval_articles(
        self,
        *,
        lookback_days: int | None = None,
        limit: int = 2000,
        since: datetime | date | None = None,
    ) -> list[DigestArticle]:
        """Load articles from recent days for the recap pipeline.

        *lookback_days* controls how many daily partitions to load
        (defaults to ``gc_retention_days``).  When *since* is given,
        only articles published **after** *since* are returned
        (``>`` for ``datetime``, ``>=`` midnight for ``date``).
        """
        days = self._load_recent_days(n=lookback_days)
        articles = self._all_articles(days)
        sorted_arts = sorted(articles.values(), key=lambda a: a.published_at, reverse=True)
        if since is not None:
            if type(since) is datetime:  # strict >; datetime is a date subclass
                sorted_arts = [a for a in sorted_arts if a.published_at > since]
            else:
                cutoff = datetime(since.year, since.month, since.day, tzinfo=UTC)
                sorted_arts = [a for a in sorted_arts if a.published_at >= cutoff]
        return [
            DigestArticle(
                article_id=a.article_id,
                title=a.title,
                url=a.url,
                source=a.source_domain,
                published_at=a.published_at.isoformat(),
                clean_text=a.clean_text or "",
            )
            for a in sorted_arts[:limit]
        ]


def _article_changed(existing: Article, article: NormalizedArticle) -> bool:
    return any(
        [
            existing.url != article.url,
            existing.url_canonical != article.url_canonical,
            existing.url_hash != article.url_hash,
            existing.title != article.title,
            existing.source_domain != article.source_domain,
            existing.published_at != article.published_at,
            existing.language_detected != article.language_detected,
            existing.content_raw != article.content_raw,
            existing.summary_raw != article.summary_raw,
            existing.is_full_content != article.is_full_content,
            existing.clean_text != article.clean_text,
            existing.clean_text_chars != article.clean_text_chars,
            existing.is_truncated != article.is_truncated,
        ],
    )


def _update_article(
    existing: Article,
    article: NormalizedArticle,
    run_id: str,  # noqa: ARG001
) -> Article:
    return Article(
        article_id=existing.article_id,
        source_name=article.source_name,
        external_id=article.external_id,
        url=article.url,
        url_canonical=article.url_canonical,
        url_hash=article.url_hash,
        title=article.title,
        source_domain=article.source_domain,
        published_at=article.published_at,
        language_detected=article.language_detected,
        clean_text=article.clean_text,
        clean_text_chars=article.clean_text_chars,
        is_full_content=article.is_full_content,
        is_truncated=article.is_truncated,
        ingested_at=existing.ingested_at,
        content_raw=article.content_raw,
        summary_raw=article.summary_raw,
        fallback_key=existing.fallback_key,
        raw_json=existing.raw_json,
    )
