"""CLI entrypoint for news-recap."""

import contextlib
import json
import logging
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text

from news_recap import __version__
from news_recap.automation import (
    ScheduleController,
    ScheduleLine,
    ScheduleMeta,
    _app_dir,
    _log_dir,
    _platform,
    resolve_rss_urls,
)
from news_recap.config import Settings
from news_recap.ingestion.controllers import (
    DailyIngestionCommand,
    IngestionCliController,
    IngestionResult,
)
from news_recap.recap.digest_info import (
    DigestInfoController,
    _fmt_dt,
    _human_elapsed,
    _human_size,
    _smart_period,
)
from news_recap.recap.export_prompt import PromptCliController, PromptCommand, PromptLine
from news_recap.recap.launcher import (
    PipelineLine,
    RecapCliController,
    RecapRunCommand,
)
from news_recap.web.server import WebCliController, WebServeCommand


def _configure_logging() -> None:
    root = logging.getLogger("news_recap")
    root.handlers.clear()
    root.addHandler(
        RichHandler(
            show_path=False,
            rich_tracebacks=True,
            markup=True,
            log_time_format="[%H:%M:%S]",
        ),
    )
    root.setLevel(logging.INFO)


class _PlainFormatter(logging.Formatter):
    """Logging formatter that strips Rich markup tags for plain-text output."""

    def format(self, record: logging.LogRecord) -> str:
        record.msg = Text.from_markup(str(record.msg)).plain
        return super().format(record)


def _configure_plain_logging() -> None:
    root = logging.getLogger("news_recap")
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        _PlainFormatter("%(asctime)s | %(levelname)-7s | %(message)s"),
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

NO_COLOR = False


@click.group()
@click.version_option(version=__version__, prog_name="news-recap")
@click.option(
    "--no-color",
    "no_color",
    is_flag=True,
    default=False,
    help="Disable colors and progress indicators (for log-friendly output).",
)
def news_recap(no_color: bool) -> None:
    """News recap CLI."""
    global NO_COLOR  # noqa: PLW0603
    NO_COLOR = no_color
    if no_color:
        _configure_plain_logging()


@news_recap.command("ingest")
@click.option(
    "--rss",
    "feed_urls",
    multiple=True,
    help="RSS/Atom feed URL. Can be repeated.",
)
def ingest(feed_urls: tuple[str, ...]) -> None:
    """Run one ingestion cycle from RSS feeds."""

    result = INGESTION_CONTROLLER.run_daily(
        DailyIngestionCommand(feed_urls=feed_urls),
    )
    _print_ingest(result)


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
    "--from-digest",
    "from_digest",
    type=click.IntRange(min=1),
    default=None,
    help="Reuse articles from an existing digest by ID (as shown by `news-recap list`).",
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
    from_digest: int | None,
    use_api_key: bool,
    max_days: int | None,
    all_articles: bool,
) -> None:
    """Create a news digest from recent articles."""

    _emit_pipeline(
        RECAP_CONTROLLER.run_pipeline(
            RecapRunCommand(
                agent_override=agent,
                article_limit=article_limit,
                stop_after=stop_after,
                fresh=fresh,
                api_mode=api_mode,
                use_api_key=use_api_key,
                from_digest=from_digest,
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
@click.option(
    "--from-digest",
    "from_digest",
    type=click.IntRange(min=1),
    default=None,
    help="Build prompt from an existing digest by ID (as shown by `news-recap list`).",
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
    from_digest: int | None,
) -> None:
    """Export a ready-to-paste LLM prompt from recent articles."""

    _emit_prompt(
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
                from_digest=from_digest,
            ),
        ),
    )


@news_recap.command("info")
@click.argument("digest_id", type=click.IntRange(min=1), default=None, required=False)
def info_cmd(digest_id: int | None) -> None:
    """Show app paths, or detailed info about a digest.

    DIGEST_ID (optional) — show details for this digest (as shown by `news-recap list`).
    """
    if digest_id is not None:
        _print_digest_detail(digest_id)
    else:
        _print_info()


@news_recap.command("list")
def list_cmd() -> None:
    """Show completed digests and uncovered article periods."""
    DIGEST_INFO_CONTROLLER.digest_info(no_color=NO_COLOR)


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
    meta = SCHEDULE_CONTROLLER.get_schedule()
    _print_schedule(meta)


@schedule_group.command("delete")
def schedule_delete() -> None:
    """Remove the daily scheduled digest job."""
    _emit_schedule(SCHEDULE_CONTROLLER.uninstall())


_MAX_HOUR = 23
_MAX_MINUTE = 59


def _validate_time(value: str) -> tuple[int, int]:
    if not re.match(r"^\d{2}:\d{2}$", value):
        raise click.BadParameter(f"Must be HH:MM format, got {value!r}")
    h, m = int(value[:2]), int(value[3:])
    if not (0 <= h <= _MAX_HOUR and 0 <= m <= _MAX_MINUTE):
        raise click.BadParameter(f"Invalid time {value!r} (hour 0-23, minute 0-59)")
    return h, m


def _emit_lines(lines: list[str] | Iterator[str]) -> None:
    for line in lines:
        click.echo(line)


def _emit_styled(severity: str, text: str) -> None:
    """Print a single severity-tagged line, respecting ``NO_COLOR``."""
    display = f"  {text}" if severity == "log" else text
    if NO_COLOR:
        click.echo(display)
    else:
        style = _SCHEDULE_STYLES.get(severity, {})
        click.secho(display, **style)  # type: ignore[arg-type]


def _emit_pipeline(lines: Iterator[PipelineLine]) -> None:
    for severity, text in lines:
        _emit_styled(severity, text)


def _emit_prompt(lines: Iterator[PromptLine]) -> None:
    for severity, text in lines:
        if severity == "text":
            click.echo(text)
        else:
            _emit_styled(severity, text)


def _print_info() -> None:
    settings = Settings.from_env()
    platform = _platform()
    data_dir = settings.data_dir.resolve()
    workdir_root = settings.orchestrator.workdir_root.resolve()
    app_dir = _app_dir(platform).resolve()
    log_dir = _log_dir(platform).resolve()

    console = Console(no_color=NO_COLOR, highlight=not NO_COLOR)

    groups: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Data",
            [
                ("Data dir", str(data_dir)),
                ("Feed cache", str(data_dir / "feeds.json")),
                ("Run history", str(data_dir / "runs.json")),
                ("Resource cache", str(data_dir / "resources")),
            ],
        ),
        (
            "Pipeline",
            [
                ("Digest workdir", str(workdir_root)),
            ],
        ),
        (
            "Automation",
            [
                ("App dir", str(app_dir)),
                ("Schedule", str(app_dir / "schedule.json")),
                ("Logs", str(log_dir)),
            ],
        ),
    ]

    for i, (heading, rows) in enumerate(groups):
        if i > 0:
            console.print()
        console.print(f"[bold]{heading}[/bold]" if not NO_COLOR else heading)
        for label, path in rows:
            padded = f"{label:<18}"
            styled = f"[cyan]{padded}[/cyan]" if not NO_COLOR else padded
            console.print(f"  {styled} {path}")


def _print_ingest(result: IngestionResult) -> None:
    s = result.summary
    fs = result.fetch_stats
    console = Console(no_color=NO_COLOR, highlight=not NO_COLOR)

    status = s.status.value
    if s.status.value == "succeeded":
        status_display = "[green]succeeded[/green]" if not NO_COLOR else "succeeded"
    elif s.status.value == "partial":
        status_display = "[yellow]partial[/yellow]" if not NO_COLOR else "partial"
    else:
        status_display = f"[red]{status}[/red]" if not NO_COLOR else status

    console.print()
    heading = "[bold]Ingestion completed[/bold]" if not NO_COLOR else "Ingestion completed"
    console.print(f"  {heading}  {status_display}")
    console.print()

    def _row(label: str, value: object) -> None:
        padded = f"{label:<14}"
        styled = f"[cyan]{padded}[/cyan]" if not NO_COLOR else padded
        console.print(f"    {styled} {value}")

    _row("Run ID", s.run_id[:12])
    _row("Ingested", s.counters.ingested_count)
    _row("Updated", s.counters.updated_count)
    _row("Skipped", s.counters.skipped_count)
    if s.counters.gaps_opened_count:
        gaps = (
            f"[yellow]{s.counters.gaps_opened_count}[/yellow]"
            if not NO_COLOR
            else str(s.counters.gaps_opened_count)
        )
        _row("Gaps", gaps)

    if fs.feeds:
        console.print()
        feeds_heading = "[bold]Feeds[/bold]" if not NO_COLOR else "Feeds"
        console.print(f"  {feeds_heading}")
        for feed in fs.feeds:
            yes = "[green]✓[/green]" if not NO_COLOR else "yes"
            no = "[dim]✗[/dim]" if not NO_COLOR else "no"
            parts = [
                f"{feed.received_items}/{feed.requested_n} items",
                feed.status,
                f"etag {yes if feed.received_etag else no}",
                f"last-modified {yes if feed.received_last_modified else no}",
            ]
            detail = "  ".join(parts)
            url = f"[cyan]{feed.feed_url}[/cyan]" if not NO_COLOR else feed.feed_url
            console.print(f"    {url}")
            console.print(f"      {detail}")

    cache_parts = [
        f"conditional={fs.requests_conditional}/{fs.feeds_total}",
        f"not-modified={fs.responses_not_modified}",
        f"fetched={fs.responses_fetched}",
    ]
    if fs.snapshot_articles:
        cache_parts.append(f"snapshot={fs.snapshot_articles} articles")
    if fs.snapshot_restored:
        cache_parts.append("resumed=yes")
    cache_line = "  ".join(cache_parts)
    console.print()
    dim_open = "[dim]" if not NO_COLOR else ""
    dim_close = "[/dim]" if not NO_COLOR else ""
    console.print(f"  {dim_open}Cache  {cache_line}{dim_close}")
    console.print()


def _collect_task_rows(workdir: Path) -> list[tuple[str, float, int, int, int]]:
    """Scan task sub-dirs for usage/size metrics."""
    rows: list[tuple[str, float, int, int, int]] = []
    for task_dir in sorted(workdir.iterdir()):
        if not task_dir.is_dir():
            continue
        elapsed, tokens = 0.0, 0
        usage_path = task_dir / "meta" / "usage.json"
        if usage_path.exists():
            with contextlib.suppress(OSError, json.JSONDecodeError, ValueError):
                data = json.loads(usage_path.read_text("utf-8"))
                elapsed = float(data.get("elapsed_seconds", 0))
                tokens = int(data.get("total_tokens") or data.get("tokens_used") or 0)
        prompt_size = output_size = 0
        with contextlib.suppress(OSError):
            prompt_size = (task_dir / "input" / "task_prompt.txt").stat().st_size
        with contextlib.suppress(OSError):
            output_size = (task_dir / "output" / "agent_stdout.log").stat().st_size
        if elapsed or tokens or prompt_size or output_size:
            rows.append((task_dir.name, elapsed, prompt_size, output_size, tokens))
    return rows


def _print_digest_detail(digest_id: int) -> None:
    s = DIGEST_INFO_CONTROLLER.digest_detail(digest_id)
    if s is None:
        click.echo(f"Digest #{digest_id} not found.")
        raise SystemExit(1)

    console = Console(no_color=NO_COLOR, highlight=not NO_COLOR)
    settings = Settings.from_env()
    workdir = settings.orchestrator.workdir_root.resolve() / s.pipeline_dir_name

    console.print()
    heading = f"[bold]Digest #{s.digest_id}[/bold]" if not NO_COLOR else f"Digest #{s.digest_id}"
    console.print(f"  {heading}")
    console.print()

    def _row(label: str, value: str) -> None:
        padded = f"{label:<16}"
        styled = f"[cyan]{padded}[/cyan]" if not NO_COLOR else padded
        console.print(f"    {styled} {value}")

    _row("Date", str(s.business_date))
    _row("Started", _fmt_dt(s.started_at))
    _row("Articles", str(s.article_count))
    _row("Article period", _smart_period(s.earliest_article, s.latest_article))
    _row("Elapsed", _human_elapsed(s.elapsed_seconds))
    _row("Prompts", _human_size(s.prompt_bytes))
    _row("Output", _human_size(s.output_bytes))
    if s.total_tokens:
        _row("Tokens", f"{s.total_tokens:,}")
    _row("Workdir", str(workdir))

    if workdir.is_dir():
        rows = _collect_task_rows(workdir)
        if rows:
            console.print()
            table = Table(show_lines=False, pad_edge=False, box=None)
            table.add_column("Phase", no_wrap=True)
            table.add_column("Elapsed", justify="right", no_wrap=True)
            table.add_column("Prompt", justify="right", no_wrap=True)
            table.add_column("Output", justify="right", no_wrap=True)
            table.add_column("Tokens", justify="right", no_wrap=True)
            for name, elapsed, prompt_sz, output_sz, tok in rows:
                table.add_row(
                    name,
                    _human_elapsed(elapsed),
                    _human_size(prompt_sz),
                    _human_size(output_sz),
                    f"{tok:,}" if tok else "—",
                )
            console.print(table)

    console.print()


def _print_schedule(meta: ScheduleMeta | None) -> None:
    console = Console(no_color=NO_COLOR, highlight=not NO_COLOR)

    if meta is None:
        console.print("No schedule configured.")
        return

    heading = "[bold]Schedule[/bold]" if not NO_COLOR else "Schedule"
    console.print()
    console.print(f"  {heading}")
    console.print()

    def _row(label: str, value: str) -> None:
        padded = f"{label:<14}"
        styled = f"[cyan]{padded}[/cyan]" if not NO_COLOR else padded
        console.print(f"    {styled} {value}")

    _row("Time", meta.time)
    _row("Agent", meta.agent or "default")
    _row("Venv", meta.venv_bin or "no (global news-recap)")

    if meta.rss_urls:
        console.print()
        feeds_heading = "[bold]Feeds[/bold]" if not NO_COLOR else "Feeds"
        console.print(f"  {feeds_heading}  ({len(meta.rss_urls)})")
        for url in meta.rss_urls:
            styled_url = f"[cyan]{url}[/cyan]" if not NO_COLOR else url
            console.print(f"    {styled_url}")

    console.print()


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
        _emit_styled(severity, text)
        if severity == "error":
            has_error = True
    if has_error:
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    news_recap()
