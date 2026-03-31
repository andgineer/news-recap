"""CLI entrypoint for news-recap."""

import logging
from collections.abc import Iterator
from pathlib import Path

import rich_click as click

from news_recap import __version__
from news_recap.automation import ScheduleController, ScheduleLine, resolve_rss_urls
from news_recap.ingestion.controllers import (
    DailyIngestionCommand,
    IngestionCliController,
)
from news_recap.recap.digest_info import DigestInfoController
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
DIGEST_INFO_CONTROLLER = DigestInfoController()
WEB_CONTROLLER = WebCliController()
SCHEDULE_CONTROLLER = ScheduleController()


@click.group()
@click.version_option(version=__version__, prog_name="news-recap")
def news_recap() -> None:
    """News recap CLI."""


@news_recap.command("ingest")
@click.option(
    "--rss",
    "feed_urls",
    multiple=True,
    help="RSS/Atom feed URL. Can be repeated.",
)
def ingest(feed_urls: tuple[str, ...]) -> None:
    """Run one ingestion cycle from RSS feeds."""

    _emit_lines(
        INGESTION_CONTROLLER.run_daily(
            DailyIngestionCommand(
                feed_urls=feed_urls,
            ),
        ),
    )


@news_recap.command("create")
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
            "oneshot_digest",
            "refine_layout",
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
    "--from-pipeline",
    "from_pipeline",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Reuse articles from an existing pipeline directory (for A/B comparisons).",
)
@click.option(
    "--use-api-key",
    "use_api_key",
    is_flag=True,
    default=False,
    help=(
        "Keep vendor API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) in the agent "
        "subprocess environment. By default they are unset so agents use their subscription."
    ),
)
@click.option(
    "--max-days",
    "max_days",
    type=click.IntRange(min=1),
    default=None,
    help="Max days to look back for articles (default: 2, env NEWS_RECAP_DIGEST_LOOKBACK_DAYS).",
)
@click.option(
    "--all",
    "all_articles",
    is_flag=True,
    default=False,
    help="Ignore previous digests; include all articles within the lookback window.",
)
def recap_run(  # noqa: PLR0913
    agent: str | None,
    article_limit: int | None,
    stop_after: str | None,
    fresh: bool,
    api_mode: bool,
    from_pipeline: Path | None,
    use_api_key: bool,
    max_days: int | None,
    all_articles: bool,
) -> None:
    """Create a news digest from recent articles."""

    _emit_lines(
        RECAP_CONTROLLER.run_pipeline(
            RecapRunCommand(
                agent_override=agent,
                article_limit=article_limit,
                stop_after=stop_after,
                fresh=fresh,
                api_mode=api_mode,
                use_api_key=use_api_key,
                from_pipeline=from_pipeline,
                max_days=max_days,
                all_articles=all_articles,
            ),
        ),
    )


@news_recap.command("prompt")
@click.option(
    "--ai/--no-ai",
    default=True,
    show_default=True,
    help=(
        "Run full classify→dedup pipeline before building the prompt "
        "(same scope as the create command)."
    ),
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
@click.option(
    "--max-days",
    "max_days",
    type=click.IntRange(min=1),
    default=None,
    help="Max days to look back for articles (default: 2, env NEWS_RECAP_DIGEST_LOOKBACK_DAYS).",
)
@click.option(
    "--all",
    "all_articles",
    is_flag=True,
    default=False,
    help="Ignore previous digests; include all articles within the lookback window.",
)
def recap_prompt(  # noqa: PLR0913
    ai: bool,
    fresh: bool,
    group_threshold: float,
    language: str,
    agent: str | None,
    out: str,
    max_days: int | None,
    all_articles: bool,
) -> None:
    """Export a ready-to-paste LLM prompt from recent articles."""

    _emit_lines(
        PROMPT_CONTROLLER.prompt(
            PromptCommand(
                group_threshold=group_threshold,
                language=language,
                out=out,
                ai=ai,
                fresh=fresh,
                agent=agent,
                max_days=max_days,
                all_articles=all_articles,
            ),
        ),
    )


@news_recap.command("list")
def list_cmd() -> None:
    """Show completed digests and uncovered article periods."""
    DIGEST_INFO_CONTROLLER.digest_info()


@news_recap.command("delete")
@click.argument("digest_id", type=click.IntRange(min=1))
def delete_cmd(digest_id: int) -> None:
    """Delete a digest so its articles become available for the next one.

    DIGEST_ID is the numeric digest ID (as shown by `news-recap list`).
    """
    _emit_lines(DIGEST_INFO_CONTROLLER.delete_digest(digest_id))


@news_recap.command("serve")
@click.argument("digest_id", type=click.IntRange(min=1), default=None, required=False)
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
    digest_id: int | None,
    host: str,
    port: int,
) -> None:
    """Start the digest web viewer.

    DIGEST_ID is the numeric digest ID (1 = latest, as shown by `news-recap list`).
    Defaults to the latest completed digest.
    """
    _emit_lines(
        WEB_CONTROLLER.serve(
            WebServeCommand(
                digest_id=digest_id,
                host=host,
                port=port,
            ),
        ),
    )


@click.group("schedule")
def schedule_group() -> None:
    """Manage daily scheduled digest creation."""


news_recap.add_command(schedule_group)


@schedule_group.command("set")
@click.option(
    "--rss",
    "rss_urls",
    multiple=True,
    help="RSS/Atom feed URL. Can be repeated.",
)
@click.option(
    "--agent",
    type=click.Choice(["codex", "claude", "gemini"], case_sensitive=False),
    default=None,
    help="LLM agent for the digest step. Omit to use the config default.",
)
@click.option(
    "--time",
    "run_time",
    default="03:00",
    show_default=True,
    help="Daily run time in HH:MM format.",
    callback=lambda _ctx, _param, value: _validate_time(value),
)
@click.option(
    "--venv",
    "use_venv",
    is_flag=True,
    default=False,
    help="Use the current Python venv binary instead of globally installed news-recap.",
)
def schedule_set(
    rss_urls: tuple[str, ...],
    agent: str | None,
    run_time: tuple[int, int],
    use_venv: bool,
) -> None:
    """Install or update the daily scheduled digest job."""
    import sys

    urls = resolve_rss_urls(rss_urls)
    venv_bin = str(Path(sys.executable).parent / "news-recap") if use_venv else None
    hour, minute = run_time
    _emit_schedule(
        SCHEDULE_CONTROLLER.install(
            urls,
            agent=agent,
            hour=hour,
            minute=minute,
            venv_bin=venv_bin,
        ),
    )


@schedule_group.command("get")
def schedule_get() -> None:
    """Show current schedule configuration."""
    _emit_schedule(SCHEDULE_CONTROLLER.get_schedule())


@schedule_group.command("delete")
def schedule_delete() -> None:
    """Remove the daily scheduled digest job."""
    _emit_schedule(SCHEDULE_CONTROLLER.uninstall())


_MAX_HOUR = 23
_MAX_MINUTE = 59


def _validate_time(value: str) -> tuple[int, int]:
    import re

    if not re.match(r"^\d{2}:\d{2}$", value):
        raise click.BadParameter(f"Must be HH:MM format, got {value!r}")
    h, m = int(value[:2]), int(value[3:])
    if not (0 <= h <= _MAX_HOUR and 0 <= m <= _MAX_MINUTE):
        raise click.BadParameter(f"Invalid time {value!r} (hour 0-23, minute 0-59)")
    return h, m


def _emit_lines(lines: list[str] | Iterator[str]) -> None:
    for line in lines:
        click.echo(line)


_SCHEDULE_STYLES: dict[str, dict[str, object]] = {
    "ok": {"fg": "green"},
    "info": {"fg": "cyan"},
    "heading": {"fg": "white", "bold": True},
    "warn": {"fg": "yellow", "bold": True},
    "error": {"fg": "red", "bold": True},
    "log": {"fg": "bright_black"},
}


def _emit_schedule(lines: Iterator[ScheduleLine]) -> None:
    has_error = False
    for severity, text in lines:
        style = _SCHEDULE_STYLES.get(severity, {})
        if severity == "log":
            click.secho(f"  {text}", **style)  # type: ignore[arg-type]
        else:
            click.secho(text, **style)  # type: ignore[arg-type]
        if severity == "error":
            has_error = True
    if has_error:
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
