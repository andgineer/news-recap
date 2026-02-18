"""CLI entrypoint for news-recap."""

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
    LlmEnqueueCommand,
    LlmInspectTaskCommand,
    LlmListTasksCommand,
    LlmMutateTaskCommand,
    LlmSmokeCommand,
    LlmWorkerCommand,
    OrchestratorCliController,
)

click.rich_click.USE_MARKDOWN = True
INGESTION_CONTROLLER = IngestionCliController()
ORCHESTRATOR_CONTROLLER = OrchestratorCliController()


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


def _emit_lines(lines: list[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
