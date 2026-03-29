"""Controllers for ingestion CLI commands."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from news_recap.config import Settings
from news_recap.ingestion.pipeline import run_daily_ingestion
from news_recap.ingestion.repository import IngestionStore
from news_recap.ingestion.sources.rss import RssSource, RssSourceConfig


@dataclass(slots=True)
class DailyIngestionCommand:
    """CLI inputs for daily ingestion command."""

    feed_urls: tuple[str, ...]


@dataclass(slots=True)
class IngestionStatsCommand:
    """CLI inputs for stats command."""

    hours: int
    source: str | None
    recent_runs: int


class IngestionCliController:
    """Coordinates ingestion command execution."""

    def run_daily(self, command: DailyIngestionCommand) -> list[str]:
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

        lines = [
            "Ingestion run completed: "
            f"run_id={summary.run_id} status={summary.status.value} "
            f"ingested={summary.counters.ingested_count} "
            f"updated={summary.counters.updated_count} "
            f"skipped={summary.counters.skipped_count} "
            f"gaps={summary.counters.gaps_opened_count}",
            "RSS conditional GET: "
            f"feeds={fetch_stats.feeds_total} "
            f"conditional={fetch_stats.requests_conditional} "
            f"not_modified={fetch_stats.responses_not_modified} "
            f"fetched={fetch_stats.responses_fetched} "
            f"received_etag={fetch_stats.responses_with_etag} "
            f"received_last_modified={fetch_stats.responses_with_last_modified} "
            f"snapshot_articles={fetch_stats.snapshot_articles} "
            f"snapshot_expired={'yes' if fetch_stats.snapshot_expired else 'no'} "
            f"resumed_snapshot={'yes' if fetch_stats.snapshot_restored else 'no'} "
            f"resume_cursor={fetch_stats.resume_cursor or '-'}",
        ]

        for feed in fetch_stats.feeds:
            lines.append(
                "  feed="
                f"{feed.feed_url} request_url={feed.request_url} "
                f"requested_n={feed.requested_n} "
                f"received_items={feed.received_items} status={feed.status} "
                f"if_none_match={'yes' if feed.sent_if_none_match else 'no'} "
                f"if_modified_since={'yes' if feed.sent_if_modified_since else 'no'} "
                f"etag={'yes' if feed.received_etag else 'no'} "
                f"last_modified={'yes' if feed.received_last_modified else 'no'}",
            )
        return lines

    def stats(self, command: IngestionStatsCommand) -> list[str]:
        settings = Settings.from_env()
        until = datetime.now(tz=UTC)
        since = until - timedelta(hours=command.hours)
        with _store(settings) as store:
            summary = store.summarize_runs(
                since=since,
                until=until,
                source=command.source,
            )
            recent = store.list_recent_runs(
                limit=command.recent_runs,
                source=command.source,
            )

        lines = [f"Window: {since.isoformat()} .. {until.isoformat()} (last {command.hours}h)"]
        if command.source:
            lines.append(f"Source filter: {command.source}")

        lines.extend(
            [
                "Runs: "
                f"{summary.runs_count} "
                f"(succeeded={summary.succeeded_runs_count}, "
                f"partial={summary.partial_runs_count}, "
                f"failed={summary.failed_runs_count}, "
                f"other={summary.other_runs_count})",
                "Articles: "
                f"ingested={summary.ingested_count} "
                f"updated={summary.updated_count} "
                f"skipped={summary.skipped_count}",
                f"Gaps opened: {summary.gaps_opened_count}",
            ],
        )

        if not recent:
            return lines

        lines.append("Recent runs:")
        for run in recent:
            finished_at = run.finished_at.isoformat() if run.finished_at is not None else "-"
            lines.append(
                f"  {run.run_id} source={run.source} status={run.status} "
                f"started={run.started_at.isoformat()} finished={finished_at} "
                f"ingested={run.ingested_count} updated={run.updated_count} "
                f"skipped={run.skipped_count} gaps={run.gaps_opened_count}",
            )
        return lines


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
