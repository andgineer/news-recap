"""CLI entrypoint for news-recap."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import rich_click as click

from news_recap import __version__
from news_recap.brain.flows import (
    FeedbackAddCommand,
    HighlightsGenerateCommand,
    IntelligenceCliController,
    IntelligenceStatsCommand,
    MonitorListCommand,
    MonitorRunCommand,
    MonitorUpsertCommand,
    QaAskCommand,
    ReadStateMarkCommand,
    StoryBuildCommand,
    StoryDefineCommand,
    StoryDetailsGenerateCommand,
    StoryListCommand,
)
from news_recap.ingestion.controllers import (
    DailyIngestionCommand,
    IngestionCliController,
    IngestionClustersCommand,
    IngestionDuplicatesCommand,
    IngestionGcCommand,
    IngestionPruneCommand,
    IngestionStatsCommand,
)
from news_recap.recap.controllers import (
    RecapCliController,
    RecapRunCommand,
)

click.rich_click.USE_MARKDOWN = True
INGESTION_CONTROLLER = IngestionCliController()
INTELLIGENCE_CONTROLLER = IntelligenceCliController()
RECAP_CONTROLLER = RecapCliController()


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


@ingest.command("gc")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    show_default=True,
    help="Show deletion counts without modifying the database.",
)
def ingest_gc(
    db_path: Path | None,
    dry_run: bool,
) -> None:
    """Run global GC for shared unreferenced records."""

    _emit_lines(
        INGESTION_CONTROLLER.gc(
            IngestionGcCommand(
                db_path=db_path,
                dry_run=dry_run,
            ),
        ),
    )


@news_recap.group()
def stories() -> None:
    """Story definition and assignment commands."""


@stories.command("define")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--story-id", default=None, help="Existing story id to update.")
@click.option("--name", required=True, help="Story name.")
@click.option("--description", required=True, help="Story description / intent.")
@click.option(
    "--target-language",
    default="en",
    show_default=True,
    help="Preferred output language for this story.",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Lower value means higher priority in assignment.",
)
@click.option(
    "--enabled/--disabled",
    default=True,
    show_default=True,
    help="Enable or disable this story.",
)
def stories_define(  # noqa: PLR0913
    db_path: Path | None,
    story_id: str | None,
    name: str,
    description: str,
    target_language: str,
    priority: int,
    enabled: bool,
) -> None:
    """Create or update one pinned story definition."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.define_story(
            StoryDefineCommand(
                db_path=db_path,
                story_id=story_id,
                name=name,
                description=description,
                target_language=target_language,
                priority=priority,
                enabled=enabled,
            ),
        ),
    )


@stories.command("list")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--all/--enabled-only",
    "include_disabled",
    default=False,
    show_default=True,
    help="Include disabled stories in listing.",
)
def stories_list(db_path: Path | None, include_disabled: bool) -> None:
    """List pinned story definitions."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.list_stories(
            StoryListCommand(
                db_path=db_path,
                include_disabled=include_disabled,
            ),
        ),
    )


@stories.command("build")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--date",
    "business_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Business date in YYYY-MM-DD. Defaults to today (UTC).",
)
def stories_build(db_path: Path | None, business_date: datetime | None) -> None:
    """Build pinned + auto story assignments for one business date."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.build_stories(
            StoryBuildCommand(
                db_path=db_path,
                business_date=business_date.date() if business_date is not None else None,
            ),
        ),
    )


@news_recap.group("highlights")
def highlights_group() -> None:
    """Highlights generation commands."""


@highlights_group.command("generate")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--date",
    "business_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Business date in YYYY-MM-DD. Defaults to today (UTC).",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Queue priority.",
)
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex", "gemini"], case_sensitive=False),
    default=None,
    help="Optional agent override.",
)
@click.option(
    "--model-profile",
    type=click.Choice(["fast", "quality"], case_sensitive=False),
    default=None,
    help="Optional model profile override.",
)
@click.option("--model", default=None, help="Optional explicit model override.")
@click.option(
    "--max-attempts",
    type=click.IntRange(min=1, max=10),
    default=3,
    show_default=True,
    help="Max execution attempts including first run.",
)
@click.option(
    "--timeout-seconds",
    type=click.IntRange(min=10, max=3600),
    default=600,
    show_default=True,
    help="Execution timeout per attempt.",
)
def highlights_generate(  # noqa: PLR0913
    db_path: Path | None,
    business_date: datetime | None,
    priority: int,
    agent: str | None,
    model_profile: str | None,
    model: str | None,
    max_attempts: int,
    timeout_seconds: int,
) -> None:
    """Generate highlights for one business date."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.generate_highlights(
            HighlightsGenerateCommand(
                db_path=db_path,
                business_date=business_date.date() if business_date is not None else None,
                priority=priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                agent=agent.lower() if agent is not None else None,
                model_profile=model_profile.lower() if model_profile is not None else None,
                model=model,
            ),
        ),
    )


@news_recap.group("story-details")
def story_details_group() -> None:
    """Detailed per-story generation commands."""


@story_details_group.command("generate")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--story-id", required=True, help="Pinned story id.")
@click.option(
    "--date",
    "business_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Business date in YYYY-MM-DD. Defaults to today (UTC).",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Queue priority.",
)
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex", "gemini"], case_sensitive=False),
    default=None,
    help="Optional agent override.",
)
@click.option(
    "--model-profile",
    type=click.Choice(["fast", "quality"], case_sensitive=False),
    default=None,
    help="Optional model profile override.",
)
@click.option("--model", default=None, help="Optional explicit model override.")
@click.option(
    "--max-attempts",
    type=click.IntRange(min=1, max=10),
    default=3,
    show_default=True,
    help="Max execution attempts including first run.",
)
@click.option(
    "--timeout-seconds",
    type=click.IntRange(min=10, max=3600),
    default=600,
    show_default=True,
    help="Execution timeout per attempt.",
)
def story_details_generate(  # noqa: PLR0913
    db_path: Path | None,
    story_id: str,
    business_date: datetime | None,
    priority: int,
    agent: str | None,
    model_profile: str | None,
    model: str | None,
    max_attempts: int,
    timeout_seconds: int,
) -> None:
    """Generate detailed update for one pinned story."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.generate_story_details(
            StoryDetailsGenerateCommand(
                db_path=db_path,
                business_date=business_date.date() if business_date is not None else None,
                story_id=story_id,
                priority=priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                agent=agent.lower() if agent is not None else None,
                model_profile=model_profile.lower() if model_profile is not None else None,
                model=model,
            ),
        ),
    )


@news_recap.group()
def monitors() -> None:
    """Monitor management and execution commands."""


@monitors.command("define")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--monitor-id", default=None, help="Existing monitor id to update.")
@click.option("--name", required=True, help="Monitor name.")
@click.option("--prompt", required=True, help="Monitor prompt.")
@click.option(
    "--cadence",
    default="daily",
    show_default=True,
    help="Cadence label used by scheduler (currently informational).",
)
@click.option(
    "--enabled/--disabled",
    default=True,
    show_default=True,
    help="Enable or disable this monitor.",
)
def monitors_define(  # noqa: PLR0913
    db_path: Path | None,
    monitor_id: str | None,
    name: str,
    prompt: str,
    cadence: str,
    enabled: bool,
) -> None:
    """Create or update one monitor definition."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.upsert_monitor(
            MonitorUpsertCommand(
                db_path=db_path,
                monitor_id=monitor_id,
                name=name,
                prompt=prompt,
                cadence=cadence,
                enabled=enabled,
            ),
        ),
    )


@monitors.command("list")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--all/--enabled-only",
    "include_disabled",
    default=False,
    show_default=True,
    help="Include disabled monitors in listing.",
)
def monitors_list(db_path: Path | None, include_disabled: bool) -> None:
    """List monitor definitions."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.list_monitors(
            MonitorListCommand(
                db_path=db_path,
                include_disabled=include_disabled,
            ),
        ),
    )


@monitors.command("run")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--date",
    "business_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Business date in YYYY-MM-DD. Defaults to today (UTC).",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Queue priority.",
)
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex", "gemini"], case_sensitive=False),
    default=None,
    help="Optional agent override.",
)
@click.option(
    "--model-profile",
    type=click.Choice(["fast", "quality"], case_sensitive=False),
    default=None,
    help="Optional model profile override.",
)
@click.option("--model", default=None, help="Optional explicit model override.")
@click.option(
    "--max-attempts",
    type=click.IntRange(min=1, max=10),
    default=3,
    show_default=True,
    help="Max execution attempts including first run.",
)
@click.option(
    "--timeout-seconds",
    type=click.IntRange(min=10, max=3600),
    default=600,
    show_default=True,
    help="Execution timeout per attempt.",
)
def monitors_run(  # noqa: PLR0913
    db_path: Path | None,
    business_date: datetime | None,
    priority: int,
    agent: str | None,
    model_profile: str | None,
    model: str | None,
    max_attempts: int,
    timeout_seconds: int,
) -> None:
    """Run enabled monitors and return answers."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.run_monitors(
            MonitorRunCommand(
                db_path=db_path,
                business_date=business_date.date() if business_date is not None else None,
                priority=priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                agent=agent.lower() if agent is not None else None,
                model_profile=model_profile.lower() if model_profile is not None else None,
                model=model,
            ),
        ),
    )


@news_recap.group()
def qa() -> None:
    """Ad-hoc question answering commands."""


@qa.command("ask")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--prompt", required=True, help="Question prompt.")
@click.option(
    "--lookback-days",
    type=click.IntRange(min=1, max=30),
    default=None,
    help="Retrieval lookback window in days; defaults to NEWS_RECAP_QA_LOOKBACK_DAYS.",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Queue priority.",
)
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex", "gemini"], case_sensitive=False),
    default=None,
    help="Optional agent override.",
)
@click.option(
    "--model-profile",
    type=click.Choice(["fast", "quality"], case_sensitive=False),
    default=None,
    help="Optional model profile override.",
)
@click.option("--model", default=None, help="Optional explicit model override.")
@click.option(
    "--max-attempts",
    type=click.IntRange(min=1, max=10),
    default=3,
    show_default=True,
    help="Max execution attempts including first run.",
)
@click.option(
    "--timeout-seconds",
    type=click.IntRange(min=10, max=3600),
    default=600,
    show_default=True,
    help="Execution timeout per attempt.",
)
def qa_ask(  # noqa: PLR0913
    db_path: Path | None,
    prompt: str,
    lookback_days: int | None,
    priority: int,
    agent: str | None,
    model_profile: str | None,
    model: str | None,
    max_attempts: int,
    timeout_seconds: int,
) -> None:
    """Run ad-hoc QA with bounded N-day retrieval."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.ask_qa(
            QaAskCommand(
                db_path=db_path,
                prompt=prompt,
                lookback_days=lookback_days,
                priority=priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                agent=agent.lower() if agent is not None else None,
                model_profile=model_profile.lower() if model_profile is not None else None,
                model=model,
            ),
        ),
    )


@news_recap.group("read-state")
def read_state_group() -> None:
    """Read/open interaction tracking commands."""


@read_state_group.command("mark")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--output-id", required=True, help="Stable output id.")
@click.option(
    "--event-type",
    type=click.Choice(["open", "view", "expand"], case_sensitive=False),
    default="open",
    show_default=True,
    help="Interaction event type.",
)
@click.option(
    "--output-block-id",
    type=click.IntRange(min=1),
    default=None,
    help="Optional block id if event is block-scoped.",
)
def read_state_mark(
    db_path: Path | None,
    output_id: str,
    event_type: str,
    output_block_id: int | None,
) -> None:
    """Record a read/open interaction for output (or output block)."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.mark_read_state(
            ReadStateMarkCommand(
                db_path=db_path,
                output_id=output_id,
                event_type=event_type.lower(),
                output_block_id=output_block_id,
            ),
        ),
    )


@news_recap.group()
def feedback() -> None:
    """Feedback commands for outputs and blocks."""


@feedback.command("add")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--output-id", required=True, help="Stable output id.")
@click.option(
    "--feedback-type",
    type=click.Choice(["like", "dislike", "hide", "pin"], case_sensitive=False),
    required=True,
    help="Feedback kind.",
)
@click.option("--value", default=None, help="Optional freeform feedback value.")
@click.option(
    "--output-block-id",
    type=click.IntRange(min=1),
    default=None,
    help="Optional block id if feedback is block-scoped.",
)
def feedback_add(
    db_path: Path | None,
    output_id: str,
    feedback_type: str,
    value: str | None,
    output_block_id: int | None,
) -> None:
    """Attach feedback to an output or one block."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.add_feedback(
            FeedbackAddCommand(
                db_path=db_path,
                output_id=output_id,
                feedback_type=feedback_type.lower(),
                value=value,
                output_block_id=output_block_id,
            ),
        ),
    )


@news_recap.group("insights")
def insights_group() -> None:
    """Observability and output inspection commands."""


@insights_group.command("stats")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--hours",
    type=click.IntRange(min=1, max=24 * 30),
    default=24,
    show_default=True,
    help="Rolling window for intelligence counters.",
)
def insights_stats(db_path: Path | None, hours: int) -> None:
    """Show domain counters for stories/outputs/engagement."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.stats(
            IntelligenceStatsCommand(
                db_path=db_path,
                hours=hours,
            ),
        ),
    )


@insights_group.command("outputs")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--kind",
    default=None,
    help="Optional output kind filter (highlights/story_details/monitor_answer/qa_answer).",
)
@click.option(
    "--date",
    "business_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Optional business date filter (YYYY-MM-DD).",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=500),
    default=20,
    show_default=True,
    help="Max outputs to print.",
)
def insights_outputs(
    db_path: Path | None,
    kind: str | None,
    business_date: datetime | None,
    limit: int,
) -> None:
    """List persisted business outputs."""

    _emit_lines(
        INTELLIGENCE_CONTROLLER.list_outputs(
            db_path=db_path,
            kind=kind,
            business_date=business_date.date() if business_date is not None else None,
            limit=limit,
        ),
    )


@news_recap.group()
def recap() -> None:
    """News digest pipeline commands."""


@recap.command("run")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
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
def recap_run(
    db_path: Path | None,
    business_date: datetime | None,
    agent: str | None,
) -> None:
    """Run the full news digest pipeline."""

    _emit_lines(
        RECAP_CONTROLLER.run_pipeline(
            RecapRunCommand(
                db_path=db_path,
                business_date=business_date.date() if business_date is not None else None,
                agent_override=agent,
            ),
        ),
    )


def _emit_lines(lines: list[str] | Iterator[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
