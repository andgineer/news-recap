"""Controller for the ``list`` and ``delete`` CLI commands."""

from __future__ import annotations

import shutil
from datetime import datetime

from rich.console import Console
from rich.table import Table

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.pipeline_setup import (
    DigestSummary,
    _list_digests,
    _load_digest_index,
    unregister_digest,
)


def _local(dt: datetime) -> datetime:
    """Convert a tz-aware datetime to local time."""
    return dt.astimezone()


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return _local(dt).strftime("%Y-%m-%d %H:%M:%S")


def _smart_period(earliest: datetime | None, latest: datetime | None) -> str:
    """Format article period, collapsing the date when start and end fall on the same day."""
    if not earliest or not latest:
        return "—"
    e = _local(earliest)
    l = _local(latest)  # noqa: E741
    e_date = e.strftime("%Y-%m-%d")
    l_date = l.strftime("%Y-%m-%d")
    if e_date == l_date:
        return f"{e_date} {e.strftime('%H:%M:%S')} .. {l.strftime('%H:%M:%S')}"
    return f"{e_date} {e.strftime('%H:%M:%S')} .. {l_date} {l.strftime('%H:%M:%S')}"


_SECS_PER_HOUR = 3600
_SECS_PER_MIN = 60


def _human_elapsed(seconds: float) -> str:
    """Format seconds into a concise human-readable duration."""
    if seconds <= 0:
        return "—"
    total = int(seconds)
    h, remainder = divmod(total, _SECS_PER_HOUR)
    m, s = divmod(remainder, _SECS_PER_MIN)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


_KB = 1024
_MB = _KB * 1024


def _human_size(n_bytes: int) -> str:
    """Format byte count as a human-readable size (KB/MB)."""
    if n_bytes <= 0:
        return "—"
    if n_bytes >= _MB:
        return f"{n_bytes / _MB:.1f} MB"
    if n_bytes >= _KB:
        return f"{n_bytes / _KB:.0f} KB"
    return f"{n_bytes} B"


_MIN_CONSOLE_WIDTH = 130


def _fmt_tokens(tokens: int) -> str:
    if tokens <= 0:
        return "—"
    return f"{tokens:,}"


def _build_digest_table(summaries: list[DigestSummary], *, show_status: bool = False) -> Table:
    has_tokens = any(s.total_tokens > 0 for s in summaries)

    table = Table(title="Digests (newest first)", show_lines=False)
    table.add_column("#", justify="right", style="bold", no_wrap=True, min_width=2)
    if show_status:
        table.add_column("Status", no_wrap=True)
    table.add_column("Date", no_wrap=True)
    table.add_column("Articles", justify="right", no_wrap=True)
    table.add_column("Coverage", no_wrap=True)
    table.add_column("Started", justify="right", no_wrap=True)
    table.add_column("Elapsed", justify="right", no_wrap=True)
    table.add_column("Prompts", justify="right", no_wrap=True)
    table.add_column("Output", justify="right", no_wrap=True)
    if has_tokens:
        table.add_column("Tokens", justify="right", no_wrap=True)

    for s in summaries:
        started = _local(s.started_at).strftime("%H:%M:%S") if s.started_at else "—"
        if s.input_article_count and s.input_article_count != s.article_count:
            articles_str = f"{s.article_count}/{s.input_article_count}"
        else:
            articles_str = str(s.article_count)
        row: list[str] = [str(s.digest_id)]
        if show_status:
            row.append(s.status)
        row += [
            str(s.run_date),
            articles_str,
            _smart_period(s.coverage_start, s.coverage_end),
            started,
            _human_elapsed(s.elapsed_seconds),
            _human_size(s.prompt_bytes),
            _human_size(s.output_bytes),
        ]
        if has_tokens:
            row.append(_fmt_tokens(s.total_tokens))
        table.add_row(*row)
    return table


def _last_successful_ingestion(store: IngestionStore) -> datetime | None:
    """Return ``finished_at`` of the latest successful ingestion run, or ``None``."""
    for run in store.list_recent_runs(limit=20):
        if run.status == "succeeded" and run.finished_at is not None:
            return run.finished_at
    return None


def _find_uncovered_periods(
    summaries: list[DigestSummary],
    *,
    latest_ingested: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    """Return (start, end) pairs for gaps between digest coverage intervals."""
    with_range = [
        s for s in summaries if s.coverage_start is not None and s.coverage_end is not None
    ]
    if not with_range:
        return []

    oldest_first = sorted(with_range, key=lambda s: s.coverage_start)  # type: ignore[arg-type]
    gaps: list[tuple[datetime, datetime]] = []
    for prev, nxt in zip(oldest_first, oldest_first[1:], strict=False):
        if prev.coverage_end < nxt.coverage_start:  # type: ignore[operator]
            gaps.append((prev.coverage_end, nxt.coverage_start))  # type: ignore[arg-type]

    if latest_ingested is not None:
        newest = oldest_first[-1]
        if newest.coverage_end < latest_ingested:  # type: ignore[operator]
            gaps.append((newest.coverage_end, latest_ingested))  # type: ignore[arg-type]

    return gaps


class DigestInfoController:
    """Show/delete completed and unfinished digests."""

    def digest_info(self, *, no_color: bool = False, show_all: bool = False) -> None:
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()

        summaries = _list_digests(workdir_root, completed_only=not show_all)

        show_status = show_all and any(s.status != "completed" for s in summaries)

        console = Console(
            width=_MIN_CONSOLE_WIDTH,
            height=25,
            no_color=no_color,
            highlight=not no_color,
        )

        if not summaries:
            console.print("No digests found.")
        else:
            console.print(_build_digest_table(summaries, show_status=show_status))

        completed = [s for s in summaries if s.status == "completed"]
        ingestion_store = IngestionStore(settings.data_dir)
        latest_ingested = _last_successful_ingestion(ingestion_store)
        gaps = _find_uncovered_periods(completed, latest_ingested=latest_ingested)
        gap_lines: list[str] = []
        for start, end in gaps:
            articles = ingestion_store.list_retrieval_articles(since=start)
            n = sum(1 for a in articles if datetime.fromisoformat(a.published_at) <= end)
            if n > 0:
                gap_lines.append(f"  {_fmt_dt(start)} .. {_fmt_dt(end)}  ({n} articles)")
        if gap_lines:
            console.print()
            console.print(
                "[bold]Uncovered periods:[/bold]" if not no_color else "Uncovered periods:",
            )
            for line in gap_lines:
                console.print(line)

    def digest_detail(self, digest_id: int) -> DigestSummary | None:
        """Return summary for a single digest, or None if not found."""
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()
        for s in _list_digests(workdir_root, completed_only=False):
            if s.digest_id == digest_id:
                return s
        return None

    def delete_digest(self, digest_id: int) -> list[str]:
        """Delete a digest (any status) by its numeric ID."""
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()

        was_completed = any(
            e.digest_id == digest_id and e.status == "completed"
            for e in _load_digest_index(workdir_root)
        )

        dir_name = unregister_digest(workdir_root, digest_id)
        if dir_name is None:
            return [f"Digest #{digest_id} not found."]

        pdir = workdir_root / dir_name
        if pdir.is_dir():
            shutil.rmtree(pdir)
        lines = [f"Deleted digest #{digest_id} ({dir_name})."]
        if was_completed:
            lines.append("Its articles are now available for the next digest.")
        return lines
