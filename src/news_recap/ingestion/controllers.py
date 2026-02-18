"""Controllers for ingestion CLI commands."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from news_recap.config import Settings
from news_recap.ingestion.models import RetentionPruneResult
from news_recap.ingestion.pipeline import run_daily_ingestion
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.ingestion.sources.rss import RssSource, RssSourceConfig


@dataclass(slots=True)
class DailyIngestionCommand:
    """CLI inputs for daily ingestion command."""

    db_path: Path | None
    feed_urls: tuple[str, ...]


@dataclass(slots=True)
class IngestionStatsCommand:
    """CLI inputs for stats command."""

    db_path: Path | None
    hours: int
    source: str | None
    recent_runs: int


@dataclass(slots=True)
class IngestionClustersCommand:
    """CLI inputs for cluster inspection command."""

    db_path: Path | None
    run_id: str | None
    source: str | None
    hours: int
    limit: int
    min_size: int
    members_per_cluster: int
    show_members: bool


@dataclass(slots=True)
class IngestionDuplicatesCommand:
    """CLI inputs for duplicate sample command."""

    db_path: Path | None
    run_id: str | None
    source: str | None
    hours: int
    limit_clusters: int
    members_per_cluster: int


@dataclass(slots=True)
class IngestionPruneCommand:
    """CLI inputs for retention prune command."""

    db_path: Path | None
    days: int | None
    dry_run: bool


@dataclass(slots=True)
class IngestionGcCommand:
    """CLI inputs for global GC command."""

    db_path: Path | None
    dry_run: bool


class IngestionCliController:
    """Coordinates ingestion command execution."""

    def run_daily(self, command: DailyIngestionCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        settings.validate_for_rss(override_feed_urls=command.feed_urls)
        feed_urls = _effective_feed_urls(command.feed_urls, settings)
        with _repository(settings) as repository:
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
                    state_store=repository,
                ),
            )
            summary = run_daily_ingestion(settings=settings, repository=repository, source=source)
            fetch_stats = source.get_last_run_fetch_stats()
            prune_result = _prune_for_retention(
                repository=repository,
                retention_days=settings.ingestion.article_retention_days,
                dry_run=False,
            )

        lines = [
            "Ingestion run completed: "
            f"run_id={summary.run_id} status={summary.status.value} "
            f"ingested={summary.counters.ingested_count} "
            f"updated={summary.counters.updated_count} "
            f"skipped={summary.counters.skipped_count} "
            f"clusters={summary.counters.dedup_clusters_count} "
            f"duplicates={summary.counters.dedup_duplicates_count} "
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
        if prune_result is None:
            lines.append("Retention prune: disabled (NEWS_RECAP_ARTICLE_RETENTION_DAYS=0)")
        else:
            lines.append(
                "Retention prune: "
                f"days={settings.ingestion.article_retention_days} "
                f"cutoff={prune_result.cutoff.isoformat()} "
                f"articles_deleted={prune_result.articles_deleted} "
                f"raw_deleted={prune_result.raw_payloads_deleted} "
                f"private_resources_deleted={prune_result.private_resources_deleted}",
            )
        return lines

    def stats(self, command: IngestionStatsCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        until = datetime.now(tz=UTC)
        since = until - timedelta(hours=command.hours)
        with _repository(settings) as repository:
            summary = repository.summarize_runs(
                since=since,
                until=until,
                source=command.source,
            )
            recent = repository.list_recent_runs(
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
                "Dedup: "
                f"clusters={summary.dedup_clusters_count} "
                f"duplicates={summary.dedup_duplicates_count}",
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
                f"skipped={run.skipped_count} clusters={run.dedup_clusters_count} "
                f"duplicates={run.dedup_duplicates_count} gaps={run.gaps_opened_count}",
            )
        return lines

    def clusters(self, command: IngestionClustersCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            run_id = self._resolve_run_id(
                repository=repository,
                run_id=command.run_id,
                source=command.source,
                hours=command.hours,
            )
            if run_id is None:
                return ["No ingestion run found for the selected scope."]

            result = repository.list_clusters_for_run(
                run_id=run_id,
                min_size=command.min_size,
                limit=command.limit,
                members_per_cluster=command.members_per_cluster,
            )

        lines = [
            f"Run: {result.run_id}",
            f"Clusters: {result.total_clusters}",
            f"Articles in listed clusters: {result.total_articles}",
            f"Showing clusters: {len(result.clusters)}",
        ]

        for cluster in result.clusters:
            lines.append(
                f"  cluster={cluster.cluster_id} size={cluster.size} "
                f"representative={cluster.representative_title} "
                f"url={cluster.representative_url}",
            )
            if not command.show_members:
                continue
            for member in cluster.members:
                role = "REP" if member.is_representative else "DUP"
                lines.append(
                    f"    {role} sim={member.similarity_to_representative:.3f} "
                    f"title={member.title} url={member.url}",
                )

        return lines

    def duplicates(self, command: IngestionDuplicatesCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            run_id = self._resolve_run_id(
                repository=repository,
                run_id=command.run_id,
                source=command.source,
                hours=command.hours,
            )
            if run_id is None:
                return ["No ingestion run found for the selected scope."]

            result = repository.list_clusters_for_run(
                run_id=run_id,
                min_size=2,
                limit=command.limit_clusters,
                members_per_cluster=command.members_per_cluster,
            )

        lines = [
            f"Run: {result.run_id}",
            f"Duplicate clusters: {result.total_clusters}",
            f"Articles in duplicate clusters: {result.total_articles}",
            f"Showing clusters: {len(result.clusters)}",
        ]
        for cluster in result.clusters:
            lines.append(
                f"  cluster={cluster.cluster_id} size={cluster.size} "
                f"representative={cluster.representative_title}",
            )
            for member in cluster.members:
                role = "REP" if member.is_representative else "DUP"
                lines.append(
                    f"    {role} sim={member.similarity_to_representative:.3f} "
                    f"title={member.title} url={member.url}",
                )
        return lines

    def prune(self, command: IngestionPruneCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        days = settings.ingestion.article_retention_days if command.days is None else command.days
        if days < 0:
            raise ValueError("--days must be >= 0.")
        with _repository(settings) as repository:
            prune_result = _prune_for_retention(
                repository=repository,
                retention_days=days,
                dry_run=command.dry_run,
            )

        if prune_result is None:
            return [
                "Retention prune skipped: days=0.",
                "Set NEWS_RECAP_ARTICLE_RETENTION_DAYS > 0 or pass --days.",
            ]

        return [
            "Retention prune completed: "
            f"days={days} dry_run={'yes' if command.dry_run else 'no'} "
            f"cutoff={prune_result.cutoff.isoformat()}",
            f"User article links deleted: {prune_result.articles_deleted}",
            f"Raw payload rows deleted: {prune_result.raw_payloads_deleted}",
            f"User private resources deleted: {prune_result.private_resources_deleted}",
        ]

    def gc(self, command: IngestionGcCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            result = repository.gc_unreferenced_articles(dry_run=command.dry_run)

        return [
            f"Global GC completed: dry_run={'yes' if command.dry_run else 'no'}",
            f"Global articles deleted: {result.articles_deleted}",
            f"Global raw payload rows deleted: {result.raw_payloads_deleted}",
            f"Public resources deleted: {result.public_resources_deleted}",
        ]

    @staticmethod
    def _resolve_run_id(
        *,
        repository: SQLiteRepository,
        run_id: str | None,
        source: str | None,
        hours: int,
    ) -> str | None:
        if run_id:
            return run_id
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        return repository.get_latest_run_id(source=source, since=since)


@contextmanager
def _repository(settings: Settings) -> Iterator[SQLiteRepository]:
    repository = SQLiteRepository(
        settings.db_path,
        user_id=settings.user_context.user_id,
        user_name=settings.user_context.user_name,
    )
    try:
        repository.init_schema()
        yield repository
    finally:
        repository.close()


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


def _prune_for_retention(
    *,
    repository: SQLiteRepository,
    retention_days: int,
    dry_run: bool,
) -> RetentionPruneResult | None:
    if retention_days <= 0:
        return None
    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    return repository.prune_articles(cutoff=cutoff, dry_run=dry_run)
