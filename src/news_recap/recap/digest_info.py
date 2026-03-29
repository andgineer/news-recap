"""Controller for the ``digest`` CLI command."""

from __future__ import annotations

from news_recap.config import Settings
from news_recap.recap.pipeline_setup import DigestSummary, _list_completed_digests

_MIN_FOR_GAP_CHECK = 2


def _fmt_dt(dt: object) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "--"  # type: ignore[union-attr]


def _format_digest_lines(summaries: list[DigestSummary]) -> list[str]:
    lines: list[str] = ["Digests (newest first):"]
    for s in summaries:
        if s.earliest_article and s.latest_article:
            period = f"{_fmt_dt(s.earliest_article)} .. {_fmt_dt(s.latest_article)}"
        else:
            period = "-- .. --"
        lines.append(
            f"  #{s.digest_id}  {s.business_date}  {s.article_count} articles  "
            f"{period}  {s.pipeline_dir_name}",
        )
    return lines


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

    def digest_info(self) -> list[str]:
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()
        summaries = _list_completed_digests(workdir_root)

        if not summaries:
            return ["No digests found."]

        lines = _format_digest_lines(summaries)

        gaps = _find_uncovered_periods(summaries)
        if gaps:
            lines.append("")
            lines.append("Uncovered periods:")
            lines.extend(gaps)

        return lines
