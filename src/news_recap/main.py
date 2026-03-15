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
    IngestionStatsCommand,
)
from news_recap.recap.export_prompt import PromptCliController, PromptCommand
from news_recap.recap.launcher import (
    RecapCliController,
    RecapRunCommand,
)
from news_recap.web.server import WebCliController, WebServeCommand


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
PROMPT_CONTROLLER = PromptCliController()
WEB_CONTROLLER = WebCliController()


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
    """Show ingestion statistics for a time window."""

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
        [
            "classify",
            "load_resources",
            "enrich",
            "deduplicate",
            "map_blocks",
            "reduce_blocks",
            "split_blocks",
            "group_sections",
            "summarize",
        ],
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
@click.option(
    "--api",
    "api_mode",
    is_flag=True,
    default=False,
    help="Use direct Anthropic API instead of CLI agents (sets backend=api, agent=claude).",
)
@click.option(
    "--single-pass",
    "single_pass",
    is_flag=True,
    default=False,
    help=(
        "Replace map→reduce→split→group→summarize with a single LLM call. "
        "Incompatible with --stop-after values for the five replaced stages."
    ),
)
def recap_run(  # noqa: PLR0913
    data_dir: Path | None,
    business_date: datetime | None,
    agent: str | None,
    article_limit: int | None,
    stop_after: str | None,
    fresh: bool,
    api_mode: bool,
    single_pass: bool,
) -> None:
    """Run the full news digest pipeline."""

    _single_pass_incompatible = {
        "map_blocks",
        "reduce_blocks",
        "split_blocks",
        "group_sections",
        "summarize",
    }
    if single_pass and stop_after in _single_pass_incompatible:
        raise click.UsageError(
            f"--single-pass is incompatible with --stop-after {stop_after}: "
            "that stage does not exist in single-pass mode.",
        )

    _emit_lines(
        RECAP_CONTROLLER.run_pipeline(
            RecapRunCommand(
                data_dir=data_dir,
                business_date=business_date.date() if business_date is not None else None,
                agent_override=agent,
                article_limit=article_limit,
                stop_after=stop_after,
                fresh=fresh,
                api_mode=api_mode,
                single_pass=single_pass,
            ),
        ),
    )


@recap.command("prompt")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
@click.option(
    "--ai/--no-ai",
    default=True,
    show_default=True,
    help="Run full classify→dedup pipeline before building the prompt (same scope as recap run).",
)
@click.option(
    "--fresh",
    is_flag=True,
    default=False,
    help="Discard any existing pipeline for today and start fresh. Ignored when --no-ai is set.",
)
@click.option(
    "--group-threshold",
    type=click.FloatRange(min=0.0, max=1.0),
    default=0.65,
    show_default=True,
    help="Cosine similarity for clustering.",
)
@click.option(
    "--language",
    default="ru",
    show_default=True,
    help="Language for task instruction.",
)
@click.option(
    "--agent",
    type=click.Choice(["codex", "claude", "gemini"], case_sensitive=False),
    default=None,
    help=(
        "LLM agent to use for classify/enrich pipeline steps. Overrides default_agent from config."
    ),
)
@click.option(
    "--out",
    type=click.Choice(["console", "clipboard"], case_sensitive=False),
    default="clipboard",
    show_default=True,
    help="Output destination.",
)
def recap_prompt(  # noqa: PLR0913
    data_dir: Path | None,
    ai: bool,
    fresh: bool,
    group_threshold: float,
    language: str,
    agent: str | None,
    out: str,
) -> None:
    """Export a ready-to-paste LLM prompt from recent articles."""

    _emit_lines(
        PROMPT_CONTROLLER.prompt(
            PromptCommand(
                data_dir=data_dir,
                group_threshold=group_threshold,
                language=language,
                out=out,
                ai=ai,
                fresh=fresh,
                agent=agent,
            ),
        ),
    )


@news_recap.command("serve")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Data directory path.",
)
@click.option(
    "--date",
    "pinned_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Pin the default landing page to this date (YYYY-MM-DD). Defaults to today UTC.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host to bind the web server to.",
)
@click.option(
    "--port",
    type=int,
    default=8080,
    show_default=True,
    help="Port to bind the web server to.",
)
def serve(
    data_dir: Path | None,
    pinned_date: datetime | None,
    host: str,
    port: int,
) -> None:
    """Start the digest web viewer."""
    WEB_CONTROLLER.serve(
        WebServeCommand(
            data_dir=data_dir,
            date=pinned_date.date() if pinned_date is not None else None,
            host=host,
            port=port,
        ),
    )


def _emit_lines(lines: list[str] | Iterator[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
