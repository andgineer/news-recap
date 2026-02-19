"""CLI entrypoint for news-recap."""

from datetime import datetime
from pathlib import Path

import rich_click as click

from news_recap import __version__
from news_recap.ingestion.controllers import (
    DailyIngestionCommand,
    IngestionCliController,
    IngestionClustersCommand,
    IngestionDuplicatesCommand,
    IngestionGcCommand,
    IngestionPruneCommand,
    IngestionStatsCommand,
)
from news_recap.orchestrator.controllers import (
    LlmBenchmarkCommand,
    LlmEnqueueCommand,
    LlmInspectTaskCommand,
    LlmListTasksCommand,
    LlmMutateTaskCommand,
    LlmSmokeCommand,
    LlmStatsCommand,
    LlmWorkerCommand,
    OrchestratorCliController,
)
from news_recap.orchestrator.intelligence import (
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

click.rich_click.USE_MARKDOWN = True
INGESTION_CONTROLLER = IngestionCliController()
ORCHESTRATOR_CONTROLLER = OrchestratorCliController()
INTELLIGENCE_CONTROLLER = IntelligenceCliController()


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
def llm() -> None:
    """Orchestrator queue and worker commands."""


@llm.command("enqueue-test")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--task-type", default="highlights", show_default=True, help="Task type.")
@click.option(
    "--prompt",
    default="Summarize top updates with source mapping.",
    show_default=True,
    help="Prompt text for demo task.",
)
@click.option(
    "--source-id",
    "source_ids",
    multiple=True,
    help="Allowed source id for strict mapping. Can be repeated.",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Lower number means higher priority.",
)
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex", "gemini"], case_sensitive=False),
    default=None,
    help="Optional target agent override for this task.",
)
@click.option(
    "--model-profile",
    type=click.Choice(["fast", "quality"], case_sensitive=False),
    default=None,
    help="Optional model profile override (fast or quality).",
)
@click.option(
    "--model",
    default=None,
    help="Optional concrete model override for this task.",
)
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
def llm_enqueue_test(  # noqa: PLR0913
    db_path: Path | None,
    task_type: str,
    prompt: str,
    source_ids: tuple[str, ...],
    priority: int,
    agent: str | None,
    model_profile: str | None,
    model: str | None,
    max_attempts: int,
    timeout_seconds: int,
) -> None:
    """Enqueue a demo task for orchestrator testing."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.enqueue_demo(
            LlmEnqueueCommand(
                db_path=db_path,
                task_type=task_type,
                prompt=prompt,
                source_ids=source_ids,
                priority=priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                agent=agent.lower() if agent is not None else None,
                model_profile=model_profile.lower() if model_profile is not None else None,
                model=model,
            ),
        ),
    )


@llm.command("worker")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--once/--loop",
    default=True,
    show_default=True,
    help="Run one claim-execute cycle or loop until idle.",
)
@click.option(
    "--max-tasks",
    type=click.IntRange(min=1),
    default=None,
    help="Optional cap for processed tasks in loop mode.",
)
def llm_worker(
    db_path: Path | None,
    once: bool,
    max_tasks: int | None,
) -> None:
    """Run LLM task worker."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.run_worker(
            LlmWorkerCommand(
                db_path=db_path,
                once=once,
                max_tasks=max_tasks,
            ),
        ),
    )


@llm.command("stats")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--hours",
    type=click.IntRange(min=1, max=24 * 30),
    default=24,
    show_default=True,
    help="Rolling window for quality/latency metrics.",
)
def llm_stats(db_path: Path | None, hours: int) -> None:
    """Show queue health, validation/retry metrics, and latency summary."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.stats(
            LlmStatsCommand(
                db_path=db_path,
                hours=hours,
            ),
        ),
    )


@llm.command("benchmark")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--task-type",
    "task_types",
    multiple=True,
    help="Task type to benchmark. Repeatable. Defaults to highlights/story/qa.",
)
@click.option(
    "--tasks-per-type",
    type=click.IntRange(min=1, max=200),
    default=10,
    show_default=True,
    help="How many tasks to enqueue per task type.",
)
@click.option(
    "--source-id",
    "source_ids",
    multiple=True,
    help="Optional source id filter (article:<article_id>). Defaults to recent user corpus.",
)
@click.option(
    "--priority",
    type=click.IntRange(min=0, max=1000),
    default=100,
    show_default=True,
    help="Priority assigned to generated benchmark tasks.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=Path("docs/reports/epic2_orchestrator_benchmark.md"),
    show_default=True,
    help="Path for markdown benchmark report.",
)
@click.option(
    "--use-benchmark-agent/--use-configured-agent",
    default=True,
    show_default=True,
    help="Use deterministic built-in benchmark agent or configured external agent command.",
)
def llm_benchmark(  # noqa: PLR0913
    db_path: Path | None,
    task_types: tuple[str, ...],
    tasks_per_type: int,
    source_ids: tuple[str, ...],
    priority: int,
    output_path: Path,
    use_benchmark_agent: bool,
) -> None:
    """Run deterministic orchestrator benchmark matrix and write report."""

    resolved_task_types = (
        tuple(dict.fromkeys(task_type.lower() for task_type in task_types))
        if task_types
        else ("highlights", "story", "qa")
    )
    _emit_lines(
        ORCHESTRATOR_CONTROLLER.benchmark(
            LlmBenchmarkCommand(
                db_path=db_path,
                task_types=resolved_task_types,
                tasks_per_type=tasks_per_type,
                source_ids=source_ids,
                priority=priority,
                output_path=output_path,
                use_benchmark_agent=use_benchmark_agent,
            ),
        ),
    )


@llm.command("tasks")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option(
    "--status",
    type=click.Choice(
        ["queued", "running", "succeeded", "failed", "timeout", "canceled"],
        case_sensitive=False,
    ),
    default=None,
    help="Optional status filter.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=500),
    default=50,
    show_default=True,
    help="Max tasks to print.",
)
def llm_tasks(
    db_path: Path | None,
    status: str | None,
    limit: int,
) -> None:
    """List orchestrator tasks."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.list_tasks(
            LlmListTasksCommand(
                db_path=db_path,
                status=status,
                limit=limit,
            ),
        ),
    )


@llm.command("inspect")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--task-id", required=True, help="Task id.")
def llm_inspect(db_path: Path | None, task_id: str) -> None:
    """Inspect one task with event history."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.inspect_task(
            LlmInspectTaskCommand(
                db_path=db_path,
                task_id=task_id,
            ),
        ),
    )


@llm.command("retry")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--task-id", required=True, help="Task id.")
def llm_retry(db_path: Path | None, task_id: str) -> None:
    """Manually re-queue a failed/timeout/canceled task."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.retry_task(
            LlmMutateTaskCommand(
                db_path=db_path,
                task_id=task_id,
            ),
        ),
    )


@llm.command("cancel")
@click.option("--db-path", type=click.Path(path_type=Path), default=None, help="SQLite DB path.")
@click.option("--task-id", required=True, help="Task id.")
def llm_cancel(db_path: Path | None, task_id: str) -> None:
    """Cancel a queued or running task."""

    _emit_lines(
        ORCHESTRATOR_CONTROLLER.cancel_task(
            LlmMutateTaskCommand(
                db_path=db_path,
                task_id=task_id,
            ),
        ),
    )


@llm.command("smoke")
@click.option(
    "--agent",
    "agents",
    multiple=True,
    type=click.Choice(["claude", "codex", "gemini"], case_sensitive=False),
    help="Agent to test. Repeat to test multiple; defaults to NEWS_RECAP_LLM_DEFAULT_AGENT.",
)
@click.option(
    "--model-profile",
    type=click.Choice(["fast", "quality"], case_sensitive=False),
    default="fast",
    show_default=True,
    help="Select fast or quality model profile for selected agent(s).",
)
@click.option(
    "--model",
    default=None,
    help="Optional explicit model id override for selected agent(s).",
)
@click.option(
    "--prompt",
    default="Reply with exactly: OK",
    show_default=True,
    help="Synthetic prompt used for run check.",
)
@click.option(
    "--expect-substring",
    default="OK",
    show_default=True,
    help="Substring required in stdout for successful run check.",
)
@click.option(
    "--timeout-seconds",
    type=click.IntRange(min=1, max=300),
    default=45,
    show_default=True,
    help="Timeout for probe/run commands.",
)
@click.option(
    "--claude-command",
    default=None,
    help=(
        "Run template for Claude CLI. Supports {model}, {prompt}, and {prompt_file}. "
        "If omitted, NEWS_RECAP_LLM_SMOKE_CLAUDE_COMMAND is used."
    ),
)
@click.option(
    "--codex-command",
    default=None,
    help=(
        "Run template for Codex CLI. Supports {model}, {prompt}, and {prompt_file}. "
        "If omitted, NEWS_RECAP_LLM_SMOKE_CODEX_COMMAND is used."
    ),
)
@click.option(
    "--gemini-command",
    default=None,
    help=(
        "Run template for Gemini CLI. Supports {model}, {prompt}, and {prompt_file}. "
        "If omitted, NEWS_RECAP_LLM_SMOKE_GEMINI_COMMAND is used."
    ),
)
def llm_smoke(  # noqa: PLR0913
    agents: tuple[str, ...],
    model_profile: str,
    model: str | None,
    prompt: str,
    expect_substring: str,
    timeout_seconds: int,
    claude_command: str | None,
    codex_command: str | None,
    gemini_command: str | None,
) -> None:
    """Run lightweight direct smoke checks for external CLI agents (no DB queue)."""

    result = ORCHESTRATOR_CONTROLLER.smoke(
        LlmSmokeCommand(
            agents=tuple(agent.lower() for agent in agents),
            model_profile=model_profile.lower(),
            model=model,
            prompt=prompt,
            expect_substring=expect_substring,
            timeout_seconds=timeout_seconds,
            claude_command=claude_command,
            codex_command=codex_command,
            gemini_command=gemini_command,
        ),
    )
    _emit_lines(result.lines)
    if not result.success:
        raise click.ClickException("LLM smoke check failed.")


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
    """Enqueue highlights generation task for one business date."""

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
    """Enqueue story details task for one pinned story."""

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
    """Enqueue monitor answer tasks for enabled monitors."""

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
    """Enqueue ad-hoc QA task with bounded N-day retrieval."""

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


def _emit_lines(lines: list[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
