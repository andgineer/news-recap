"""Controller for the ``list`` and ``delete`` CLI commands."""

from __future__ import annotations

import shutil
from datetime import datetime

from rich.console import Console
from rich.table import Table

from news_recap.config import Settings
from news_recap.recap.pipeline_setup import (
    DigestSummary,
    _list_completed_digests,
    unregister_digest,
)

_MIN_FOR_GAP_CHECK = 2


def _local(dt: datetime) -> datetime:
    """Convert a tz-aware datetime to local time."""
    return dt.astimezone()


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return _local(dt).strftime("%Y-%m-%d %H:%M")


def _smart_period(earliest: datetime | None, latest: datetime | None) -> str:
    """Format article period, collapsing the date when start and end fall on the same day."""
    if not earliest or not latest:
        return "—"
    e = _local(earliest)
    l = _local(latest)  # noqa: E741
    e_date = e.strftime("%Y-%m-%d")
    l_date = l.strftime("%Y-%m-%d")
    if e_date == l_date:
        return f"{e_date} {e.strftime('%H:%M')} .. {l.strftime('%H:%M')}"
    return f"{e_date} {e.strftime('%H:%M')} .. {l_date} {l.strftime('%H:%M')}"


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


_MIN_CONSOLE_WIDTH = 120


def _fmt_tokens(tokens: int) -> str:
    if tokens <= 0:
        return "—"
    return f"{tokens:,}"


def _build_digest_table(summaries: list[DigestSummary]) -> Table:
    has_tokens = any(s.total_tokens > 0 for s in summaries)

    table = Table(title="Digests (newest first)", show_lines=False)
    table.add_column("#", justify="right", style="bold", no_wrap=True)
    table.add_column("Date", no_wrap=True)
    table.add_column("Articles", justify="right", no_wrap=True)
    table.add_column("Article period", no_wrap=True)
    table.add_column("Started", justify="right", no_wrap=True)
    table.add_column("Elapsed", justify="right", no_wrap=True)
    table.add_column("Prompts", justify="right", no_wrap=True)
    table.add_column("Output", justify="right", no_wrap=True)
    if has_tokens:
        table.add_column("Tokens", justify="right", no_wrap=True)

    for s in summaries:
        started = _local(s.started_at).strftime("%H:%M") if s.started_at else "—"
        row = [
            str(s.digest_id),
            str(s.business_date),
            str(s.article_count),
            _smart_period(s.earliest_article, s.latest_article),
            started,
            _human_elapsed(s.elapsed_seconds),
            _human_size(s.prompt_bytes),
            _human_size(s.output_bytes),
        ]
        if has_tokens:
            row.append(_fmt_tokens(s.total_tokens))
        table.add_row(*row)
    return table


def _find_uncovered_periods(
    summaries: list[DigestSummary],
) -> list[str]:
    with_range = [
        s for s in summaries if s.earliest_article is not None and s.latest_article is not None
    ]
    if len(with_range) < _MIN_FOR_GAP_CHECK:
        return []

    oldest_first = sorted(with_range, key=lambda s: s.earliest_article)  # type: ignore[arg-type]
    gaps: list[str] = []
    for prev, nxt in zip(oldest_first, oldest_first[1:], strict=False):
        if prev.latest_article < nxt.earliest_article:  # type: ignore[operator]
            gaps.append(f"  {_fmt_dt(prev.latest_article)} .. {_fmt_dt(nxt.earliest_article)}")
    return gaps


class DigestInfoController:
    """Show completed digests and uncovered article periods."""

    def digest_info(self, *, no_color: bool = False) -> None:
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()
        summaries = _list_completed_digests(workdir_root)

        console = Console(
            width=_MIN_CONSOLE_WIDTH,
            height=25,
            no_color=no_color,
            highlight=not no_color,
        )

        if not summaries:
            console.print("No digests found.")
            return

        console.print(_build_digest_table(summaries))

        gaps = _find_uncovered_periods(summaries)
        if gaps:
            console.print()
            console.print(
                "[bold]Uncovered periods:[/bold]" if not no_color else "Uncovered periods:",
            )
            for g in gaps:
                console.print(g)

    def digest_detail(self, digest_id: int) -> DigestSummary | None:
        """Return summary for a single digest, or None if not found."""
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()
        for s in _list_completed_digests(workdir_root):
            if s.digest_id == digest_id:
                return s
        return None

    def delete_digest(self, digest_id: int) -> list[str]:
        """Delete a completed digest, making its articles available for the next one."""
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()

        dir_name = unregister_digest(workdir_root, digest_id)
        if dir_name is None:
            return [f"Digest #{digest_id} not found."]

        pdir = workdir_root / dir_name
        if pdir.is_dir():
            shutil.rmtree(pdir)
        return [
            f"Deleted digest #{digest_id} ({dir_name}).",
            "Its articles are now available for the next digest.",
        ]
