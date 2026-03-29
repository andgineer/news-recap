"""CLI entrypoint for news-recap."""

import copy as _copy
import logging
from collections.abc import Iterator
from pathlib import Path

import rich_click as click

from news_recap import __version__
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


@click.group()
@click.version_option(version=__version__, prog_name="news-recap")
def news_recap() -> None:
    """News recap CLI."""


@news_recap.command("ingest")
@click.option(
    "--feed-url",
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


@news_recap.command("recap")
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
    """Run the full news digest pipeline."""

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
        "(same scope as the recap command)."
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
    _emit_lines(DIGEST_INFO_CONTROLLER.digest_info())


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


_run_alias = _copy.copy(recap_run)
_run_alias.hidden = True
news_recap.add_command(_run_alias, "run")

_digest_alias = _copy.copy(list_cmd)
_digest_alias.hidden = True
news_recap.add_command(_digest_alias, "digest")


def _emit_lines(lines: list[str] | Iterator[str]) -> None:
    for line in lines:
        click.echo(line)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
