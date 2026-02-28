"""CLI entrypoint for news-recap."""

import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import rich_click as click

from news_recap import __version__
from news_recap.ingestion.controllers import (
    DailyIngestionCommand,
    IngestionCliController,
    IngestionClustersCommand,
    IngestionDuplicatesCommand,
    IngestionStatsCommand,
)
from news_recap.recap.launcher import (
    RecapCliController,
    RecapRunCommand,
)


def _configure_logging() -> None:
    root = logging.getLogger("news_recap")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s - %(message)s"),
        )
        root.addHandler(handler)
    root.setLevel(logging.INFO)


_configure_logging()

click.rich_click.USE_MARKDOWN = True
INGESTION_CONTROLLER = IngestionCliController()
RECAP_CONTROLLER = RecapCliController()


@click.group()
@click.version_option(version=__version__, prog_name="news-recap")
def news_recap() -> None:
    """News recap CLI."""


@news_recap.group()
def ingest() -> None:
    """Ingestion commands."""


@ingest.command("daily")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
@click.option(
    "--feed-url",
    "feed_urls",
    multiple=True,
    help="RSS/Atom feed URL. Can be repeated.",
)
def ingest_daily(data_dir: Path | None, feed_urls: tuple[str, ...]) -> None:
    """Run one daily ingestion cycle from RSS feeds."""

    _emit_lines(
        INGESTION_CONTROLLER.run_daily(
            DailyIngestionCommand(
                data_dir=data_dir,
                feed_urls=feed_urls,
            ),
        ),
    )


@ingest.command("stats")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
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
    data_dir: Path | None,
    hours: int,
    source: str | None,
    recent_runs: int,
) -> None:
    """Show ingestion and dedup statistics for a time window."""

    _emit_lines(
        INGESTION_CONTROLLER.stats(
            IngestionStatsCommand(
                data_dir=data_dir,
                hours=hours,
                source=source,
                recent_runs=recent_runs,
            ),
        ),
    )


@ingest.command("clusters")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
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
    data_dir: Path | None,
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
                data_dir=data_dir,
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
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
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
    data_dir: Path | None,
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
                data_dir=data_dir,
                run_id=run_id,
                source=source,
                hours=hours,
                limit_clusters=limit_clusters,
                members_per_cluster=members_per_cluster,
            ),
        ),
    )


@news_recap.group()
def recap() -> None:
    """News digest pipeline commands."""


@recap.command("run")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
@click.option(
    "--date",
    "business_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Business date in YYYY-MM-DD. Defaults to today (UTC).",
)
@click.option(
    "--agent",
    type=click.Choice(["codex", "claude", "gemini"], case_sensitive=False),
    default=None,
    help="LLM agent to use for all pipeline steps. Overrides default_agent from config.",
)
@click.option(
    "--limit",
    "article_limit",
    type=click.IntRange(min=1),
    default=None,
    help="Cap number of articles loaded (useful for smoke tests).",
)
@click.option(
    "--stop-after",
    "stop_after",
    type=click.Choice(
        ["classify", "enrich", "group", "enrich_full", "synthesize", "compose"],
        case_sensitive=False,
    ),
    default=None,
    help="Stop pipeline after this phase (e.g. --stop-after classify).",
)
@click.option(
    "--fresh",
    is_flag=True,
    default=False,
    help="Ignore any incomplete pipeline and start a new one.",
)
def recap_run(  # noqa: PLR0913
    data_dir: Path | None,
    business_date: datetime | None,
    agent: str | None,
    article_limit: int | None,
    stop_after: str | None,
    fresh: bool,
) -> None:
    """Run the full news digest pipeline."""

    _emit_lines(
        RECAP_CONTROLLER.run_pipeline(
            RecapRunCommand(
                data_dir=data_dir,
                business_date=business_date.date() if business_date is not None else None,
                agent_override=agent,
                article_limit=article_limit,
                stop_after=stop_after,
                fresh=fresh,
            ),
        ),
    )


def _emit_lines(lines: list[str] | Iterator[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
