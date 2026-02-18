"""CLI entrypoint for news-recap."""

from pathlib import Path

import rich_click as click

from news_recap import __version__
from news_recap.ingestion.controllers import (
    DailyIngestionCommand,
    IngestionCliController,
    IngestionClustersCommand,
    IngestionDuplicatesCommand,
    IngestionPruneCommand,
    IngestionStatsCommand,
)

click.rich_click.USE_MARKDOWN = True
INGESTION_CONTROLLER = IngestionCliController()


@click.group()
@click.version_option(version=__version__, prog_name="news-recap")
def news_recap() -> None:
    """News recap CLI."""


@news_recap.group()
def ingest() -> None:
    """Ingestion commands."""


@ingest.command("daily")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--feed-url",
    "feed_urls",
    multiple=True,
    help="RSS/Atom feed URL. Can be repeated.",
)
def ingest_daily(db_path: Path | None, feed_urls: tuple[str, ...]) -> None:
    """Run one daily ingestion cycle from RSS feeds."""

    _emit_lines(
        INGESTION_CONTROLLER.run_daily(
            DailyIngestionCommand(
                db_path=db_path,
                feed_urls=feed_urls,
            ),
        ),
    )


@ingest.command("stats")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--hours",
    type=click.IntRange(min=1),
    default=24,
    show_default=True,
    help="Time window for aggregation.",
)
@click.option(
    "--source",
    default=None,
    help="Optional source filter, for example rss.",
)
@click.option(
    "--recent-runs",
    type=click.IntRange(min=1, max=50),
    default=5,
    show_default=True,
    help="How many latest runs to display.",
)
def ingest_stats(
    db_path: Path | None,
    hours: int,
    source: str | None,
    recent_runs: int,
) -> None:
    """Show ingestion and dedup statistics for a time window."""

    _emit_lines(
        INGESTION_CONTROLLER.stats(
            IngestionStatsCommand(
                db_path=db_path,
                hours=hours,
                source=source,
                recent_runs=recent_runs,
            ),
        ),
    )


@ingest.command("clusters")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--run-id", default=None, help="Specific ingestion run id to inspect.")
@click.option(
    "--source",
    default=None,
    help="Optional source filter used to resolve latest run when --run-id is not provided.",
)
@click.option(
    "--hours",
    type=click.IntRange(min=1),
    default=24,
    show_default=True,
    help="Lookback window for latest run selection when --run-id is omitted.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=1000),
    default=20,
    show_default=True,
    help="Max number of clusters to print.",
)
@click.option(
    "--min-size",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Only show clusters with at least this many articles.",
)
@click.option(
    "--members-per-cluster",
    type=click.IntRange(min=1, max=20),
    default=3,
    show_default=True,
    help="How many articles per cluster to print when --show-members is enabled.",
)
@click.option(
    "--show-members/--no-show-members",
    default=False,
    show_default=True,
    help="Print sample member articles for each cluster.",
)
def ingest_clusters(  # noqa: PLR0913
    db_path: Path | None,
    run_id: str | None,
    source: str | None,
    hours: int,
    limit: int,
    min_size: int,
    members_per_cluster: int,
    show_members: bool,
) -> None:
    """Show dedup cluster sizes for one run."""

    _emit_lines(
        INGESTION_CONTROLLER.clusters(
            IngestionClustersCommand(
                db_path=db_path,
                run_id=run_id,
                source=source,
                hours=hours,
                limit=limit,
                min_size=min_size,
                members_per_cluster=members_per_cluster,
                show_members=show_members,
            ),
        ),
    )


@ingest.command("duplicates")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--run-id", default=None, help="Specific ingestion run id to inspect.")
@click.option(
    "--source",
    default=None,
    help="Optional source filter used to resolve latest run when --run-id is not provided.",
)
@click.option(
    "--hours",
    type=click.IntRange(min=1),
    default=24,
    show_default=True,
    help="Lookback window for latest run selection when --run-id is omitted.",
)
@click.option(
    "--limit-clusters",
    type=click.IntRange(min=1, max=1000),
    default=10,
    show_default=True,
    help="How many duplicate clusters to print.",
)
@click.option(
    "--members-per-cluster",
    type=click.IntRange(min=2, max=20),
    default=5,
    show_default=True,
    help="How many cluster members to show for each duplicate example.",
)
def ingest_duplicates(  # noqa: PLR0913
    db_path: Path | None,
    run_id: str | None,
    source: str | None,
    hours: int,
    limit_clusters: int,
    members_per_cluster: int,
) -> None:
    """Show sample articles recognized as duplicates (cluster size >= 2)."""

    _emit_lines(
        INGESTION_CONTROLLER.duplicates(
            IngestionDuplicatesCommand(
                db_path=db_path,
                run_id=run_id,
                source=source,
                hours=hours,
                limit_clusters=limit_clusters,
                members_per_cluster=members_per_cluster,
            ),
        ),
    )


@ingest.command("prune")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--days",
    type=click.IntRange(min=0),
    default=None,
    help=(
        "Delete user-article links older than this many days by discovered_at. "
        "Defaults to NEWS_RECAP_ARTICLE_RETENTION_DAYS."
    ),
)
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    show_default=True,
    help="Show deletion counts without modifying the database.",
)
def ingest_prune(
    db_path: Path | None,
    days: int | None,
    dry_run: bool,
) -> None:
    """Delete old articles according to retention policy."""

    _emit_lines(
        INGESTION_CONTROLLER.prune(
            IngestionPruneCommand(
                db_path=db_path,
                days=days,
                dry_run=dry_run,
            ),
        ),
    )


def _emit_lines(lines: list[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
