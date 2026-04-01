"""Controllers for ingestion CLI commands."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from news_recap.config import Settings
from news_recap.ingestion.pipeline import IngestionSummary, run_daily_ingestion
from news_recap.ingestion.repository import IngestionStore
from news_recap.ingestion.sources.rss import RssRunFetchStats, RssSource, RssSourceConfig


@dataclass(slots=True)
class DailyIngestionCommand:
    """CLI inputs for daily ingestion command."""

    feed_urls: tuple[str, ...]


@dataclass(slots=True)
class IngestionResult:
    """Structured result of one ingestion CLI run."""

    summary: IngestionSummary
    fetch_stats: RssRunFetchStats


class IngestionCliController:
    """Coordinates ingestion command execution."""

    def run_daily(self, command: DailyIngestionCommand) -> IngestionResult:
        settings = Settings.from_env()
        settings.validate_for_rss(override_feed_urls=command.feed_urls)
        feed_urls = _effective_feed_urls(command.feed_urls, settings)
        with _store(settings) as store:
            source = RssSource(
                RssSourceConfig(
                    feed_urls=feed_urls,
                    default_items_per_feed=settings.rss.default_items_per_feed,
                    per_feed_items=_effective_per_feed_items(feed_urls, settings),
                    snapshot_max_age_seconds=_snapshot_max_age_seconds(
                        settings.rss.snapshot_max_age_hours,
                    ),
                    max_retries=settings.rss.max_retries,
                    retry_backoff_seconds=settings.rss.retry_backoff_seconds,
                    request_timeout_seconds=settings.rss.request_timeout_seconds,
                    state_store=store,
                ),
            )
            summary = run_daily_ingestion(settings=settings, store=store, source=source)
            fetch_stats = source.get_last_run_fetch_stats()

        return IngestionResult(summary=summary, fetch_stats=fetch_stats)


@contextmanager
def _store(settings: Settings) -> Iterator[IngestionStore]:
    store = IngestionStore(
        settings.data_dir,
        gc_retention_days=settings.ingestion.gc_retention_days,
    )
    try:
        store.init_schema()
        yield store
    finally:
        store.close()


def _effective_feed_urls(
    override_feed_urls: tuple[str, ...],
    settings: Settings,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            url.strip() for url in (override_feed_urls or settings.rss.feed_urls) if url.strip()
        ),
    )


def _effective_per_feed_items(feed_urls: tuple[str, ...], settings: Settings) -> dict[str, int]:
    return {
        feed_url: settings.rss.per_feed_items.get(feed_url, settings.rss.default_items_per_feed)
        for feed_url in feed_urls
    }


def _snapshot_max_age_seconds(hours: int) -> int | None:
    if hours <= 0:
        return None
    return hours * 3600
