"""Shared helpers for setting up a recap pipeline directory.

Used by both ``launcher.py`` (``recap`` command) and ``export_prompt.py`` (``prompt`` command).
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import msgspec

from news_recap.config import Settings
from news_recap.recap.agents.routing import RoutingDefaults
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import _DEFAULT_MIN_RESOURCE_CHARS
from news_recap.storage.io import load_msgspec, save_msgspec

logger = logging.getLogger(__name__)

_DIGEST_FILENAME = "digest.json"
_DIGEST_INDEX_FILENAME = "digests.json"


class DigestIndexEntry(msgspec.Struct):
    """Metadata for a digest run, stored in the index."""

    digest_id: int
    pipeline_dir_name: str
    run_date: str
    article_count: int
    status: str = "completed"
    coverage_start: str | None = None
    coverage_end: str | None = None
    started_at: str | None = None
    elapsed_seconds: float = 0.0
    total_tokens: int = 0
    prompt_bytes: int = 0
    output_bytes: int = 0


def _load_digest_index(workdir_root: Path) -> list[DigestIndexEntry]:
    """Load the digest index from ``digests.json``, or return ``[]``."""
    path = workdir_root / _DIGEST_INDEX_FILENAME
    if not path.exists():
        return []
    try:
        return load_msgspec(path, list[DigestIndexEntry])
    except Exception:  # noqa: BLE001
        logger.warning("Cannot read digest index %s, starting fresh", path)
        return []


def _save_digest_index(workdir_root: Path, entries: list[DigestIndexEntry]) -> None:
    """Atomically write the digest index."""
    save_msgspec(workdir_root / _DIGEST_INDEX_FILENAME, entries)


def _next_free_id(entries: list[DigestIndexEntry]) -> int:
    """Return the smallest positive integer not used as a digest ID."""
    used = {e.digest_id for e in entries}
    n = 1
    while n in used:
        n += 1
    return n


def _build_routing_defaults(settings: Settings) -> RoutingDefaults:
    """Build RoutingDefaults from Settings for the recap pipeline."""
    return RoutingDefaults(
        default_agent=settings.orchestrator.default_agent,
        task_model_map=settings.orchestrator.task_model_map,
        command_templates={
            "claude": settings.orchestrator.claude_command_template,
            "codex": settings.orchestrator.codex_command_template,
            "gemini": settings.orchestrator.gemini_command_template,
        },
        task_type_timeout_map=settings.orchestrator.task_type_timeout_map,
        agent_max_parallel=settings.orchestrator.agent_max_parallel,
        agent_launch_delay=settings.orchestrator.agent_launch_delay,
        execution_backend=settings.orchestrator.execution_backend,
        api_model_map=settings.orchestrator.api_model_map,
        api_max_parallel=settings.orchestrator.api_max_parallel,
        api_concurrency_recovery_successes=settings.orchestrator.api_concurrency_recovery_successes,
        api_downshift_pause_seconds=settings.orchestrator.api_downshift_pause_seconds,
        api_retry_max_backoff_seconds=settings.orchestrator.api_retry_max_backoff_seconds,
        api_retry_jitter_seconds=settings.orchestrator.api_retry_jitter_seconds,
        agent_api_key_vars=dict(settings.orchestrator.agent_api_key_vars),
    )


@dataclass(slots=True)
class DigestSummary:
    """Metadata for a single digest."""

    digest_id: int
    run_date: date
    article_count: int
    coverage_start: datetime | None
    coverage_end: datetime | None
    pipeline_dir_name: str
    status: str = "completed"
    started_at: datetime | None = None
    elapsed_seconds: float = 0.0
    total_tokens: int = 0
    prompt_bytes: int = 0
    output_bytes: int = 0


def _find_last_digest_cutoff(workdir_root: Path) -> date | datetime | None:
    """Return the cutoff from the most recent completed digest.

    When ``coverage_end`` is recorded, returns its ``datetime`` (callers
    apply strict ``>`` so the boundary article is excluded).  Otherwise falls
    back to ``run_date`` as a plain ``date`` (callers apply ``>=`` midnight
    so all articles from that day are included).
    Returns ``None`` when no completed digests exist.
    """
    completed = [e for e in _load_digest_index(workdir_root) if e.status == "completed"]
    if not completed:
        return None
    newest = max(completed, key=lambda e: e.pipeline_dir_name)
    if newest.coverage_end:
        return datetime.fromisoformat(newest.coverage_end)
    return date.fromisoformat(newest.run_date)


_PIPELINE_NAME_PARTS = 5


def _parse_pipeline_start(dir_name: str) -> datetime | None:
    """Extract UTC start time from ``pipeline-YYYY-MM-DD-HHMMSS``."""
    parts = dir_name.split("-")
    if len(parts) < _PIPELINE_NAME_PARTS:
        return None
    try:
        d = date.fromisoformat(f"{parts[1]}-{parts[2]}-{parts[3]}")
        t = parts[4]
        return datetime(d.year, d.month, d.day, int(t[:2]), int(t[2:4]), int(t[4:6]), tzinfo=UTC)
    except (ValueError, IndexError):
        return None


@dataclass(slots=True)
class _UsageStats:
    elapsed: float = 0.0
    tokens: int = 0
    prompt_bytes: int = 0
    output_bytes: int = 0


def _aggregate_usage(pdir: Path) -> _UsageStats:
    """Collect usage metrics from all task workdirs.

    Field names in usage.json must stay in sync with ``_save_usage`` /
    ``read_agent_usage`` in ``agents/ai_agent.py`` and ``agents/api_agent.py``.
    """
    stats = _UsageStats()
    for task_dir in pdir.iterdir():
        if not task_dir.is_dir():
            continue
        usage_path = task_dir / "meta" / "usage.json"
        if usage_path.exists():
            try:
                data = json.loads(usage_path.read_text("utf-8"))
                stats.elapsed += float(data.get("elapsed_seconds", 0))
                stats.tokens += int(data.get("total_tokens") or data.get("tokens_used") or 0)
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        prompt = task_dir / "input" / "task_prompt.txt"
        with contextlib.suppress(OSError):
            stats.prompt_bytes += prompt.stat().st_size
        output = task_dir / "output" / "agent_stdout.log"
        with contextlib.suppress(OSError):
            stats.output_bytes += output.stat().st_size
    return stats


def create_digest_entry(
    workdir_root: Path,
    dir_name: str,
    run_date: str,
    article_count: int,
    coverage_start: str | None = None,
) -> int:
    """Allocate a digest ID and write a ``running`` entry to the index.

    Returns the assigned digest ID.
    """
    entries = _load_digest_index(workdir_root)
    started = _parse_pipeline_start(dir_name)
    entry = DigestIndexEntry(
        digest_id=_next_free_id(entries),
        pipeline_dir_name=dir_name,
        run_date=run_date,
        article_count=article_count,
        status="running",
        coverage_start=coverage_start,
        started_at=started.isoformat() if started else None,
    )
    entries.append(entry)
    _save_digest_index(workdir_root, entries)
    logger.info("Created digest #%d (%s)", entry.digest_id, dir_name)
    return entry.digest_id


def ensure_digest_entry(workdir_root: Path, pdir: Path, digest: Digest) -> None:
    """Create an index entry for *pdir* if one doesn't already exist.

    Used when resuming a legacy pipeline that was created before early-ID
    assignment was introduced.
    """
    entries = _load_digest_index(workdir_root)
    if any(e.pipeline_dir_name == pdir.name for e in entries):
        return
    create_digest_entry(
        workdir_root,
        pdir.name,
        digest.run_date,
        len(digest.articles),
        coverage_start=digest.coverage_start,
    )


def finalize_digest_entry(workdir_root: Path, pdir: Path, digest: Digest) -> None:
    """Update an existing index entry with final status and usage stats.

    Sets status to ``digest.status``, fills ``coverage_end`` and usage
    metrics.  No-op if no matching entry exists (legacy pipeline dirs).
    """
    entries = _load_digest_index(workdir_root)
    dir_name = pdir.name
    for e in entries:
        if e.pipeline_dir_name == dir_name:
            e.status = digest.status
            e.coverage_end = digest.coverage_end
            e.article_count = len(digest.articles)
            usage = _aggregate_usage(pdir)
            e.elapsed_seconds = usage.elapsed
            e.total_tokens = usage.tokens
            e.prompt_bytes = usage.prompt_bytes
            e.output_bytes = usage.output_bytes
            _save_digest_index(workdir_root, entries)
            logger.info("Finalized digest (%s) → %s", dir_name, digest.status)
            return


def unregister_digest(workdir_root: Path, digest_id: int) -> str | None:
    """Remove a digest from the index. Returns the ``pipeline_dir_name`` or ``None``."""
    entries = _load_digest_index(workdir_root)
    for i, e in enumerate(entries):
        if e.digest_id == digest_id:
            removed = entries.pop(i)
            _save_digest_index(workdir_root, entries)
            return removed.pipeline_dir_name
    return None


def _entry_to_summary(e: DigestIndexEntry) -> DigestSummary:
    return DigestSummary(
        digest_id=e.digest_id,
        run_date=date.fromisoformat(e.run_date),
        article_count=e.article_count,
        coverage_start=(datetime.fromisoformat(e.coverage_start) if e.coverage_start else None),
        coverage_end=(datetime.fromisoformat(e.coverage_end) if e.coverage_end else None),
        pipeline_dir_name=e.pipeline_dir_name,
        status=e.status,
        started_at=datetime.fromisoformat(e.started_at) if e.started_at else None,
        elapsed_seconds=e.elapsed_seconds,
        total_tokens=e.total_tokens,
        prompt_bytes=e.prompt_bytes,
        output_bytes=e.output_bytes,
    )


def _list_digests(
    workdir_root: Path,
    *,
    completed_only: bool = True,
) -> list[DigestSummary]:
    """Return digest summaries newest-first, optionally filtered to completed."""
    entries = _load_digest_index(workdir_root)
    if completed_only:
        entries = [e for e in entries if e.status == "completed"]
    newest_first = sorted(entries, key=lambda e: e.pipeline_dir_name, reverse=True)
    return [_entry_to_summary(e) for e in newest_first]


def _find_digest_pipeline_dir(workdir_root: Path, digest_id: int) -> Path | None:
    """Return the pipeline directory for the given stable *digest_id*."""
    for e in _load_digest_index(workdir_root):
        if e.digest_id == digest_id:
            return workdir_root / e.pipeline_dir_name
    return None


def _find_latest_digest_pipeline_dir(workdir_root: Path) -> Path | None:
    """Return the pipeline directory of the newest completed digest."""
    completed = [e for e in _load_digest_index(workdir_root) if e.status == "completed"]
    if not completed:
        return None
    newest = max(completed, key=lambda e: e.pipeline_dir_name)
    return workdir_root / newest.pipeline_dir_name


def gc_old_pipelines(workdir_root: Path, *, keep_days: int = 7) -> list[Path]:
    """Delete pipeline directories whose business date is outside the retention window.

    Works like ``gc_old_days`` in ``storage/io.py`` but targets pipeline dirs.
    Also removes matching entries from ``digests.json``.
    Returns the list of deleted directories.
    """
    if not workdir_root.is_dir():
        return []

    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    deleted: list[Path] = []

    for pdir in workdir_root.iterdir():
        if not pdir.is_dir() or not pdir.name.startswith("pipeline-"):
            continue
        try:
            dir_date = pdir.name.split("-", 1)[1].rsplit("-", 1)[0]
        except (ValueError, IndexError):
            continue
        if dir_date <= cutoff:
            shutil.rmtree(pdir)
            deleted.append(pdir)
            logger.debug("GC: removed old pipeline %s", pdir.name)

    if deleted:
        deleted_names = {p.name for p in deleted}
        entries = _load_digest_index(workdir_root)
        cleaned = [e for e in entries if e.pipeline_dir_name not in deleted_names]
        if len(cleaned) != len(entries):
            _save_digest_index(workdir_root, cleaned)

    return deleted


def _compute_article_window(
    settings: Settings,
    all_articles: bool,
    max_days: int | None,
) -> tuple[int, date | datetime]:
    """Return ``(lookback_days, since)`` for article retrieval.

    *since* is a ``datetime`` when anchored to the last completed digest
    (strict ``>`` filter excludes the boundary article), or a ``date``
    when only the lookback-days cap applies (``>=`` midnight).
    When *all_articles* is ``True`` the last-digest anchor is skipped
    and only the cap applies.
    """
    cap_days = max_days or settings.ingestion.digest_lookback_days
    today = datetime.now(tz=UTC).date()
    cap_cutoff = today - timedelta(days=cap_days)

    last_cutoff: date | datetime | None = None
    if not all_articles:
        last_cutoff = _find_last_digest_cutoff(
            settings.orchestrator.workdir_root.resolve(),
        )

    if last_cutoff is None:
        return cap_days, cap_cutoff
    if type(last_cutoff) is datetime:
        cap_cutoff_dt = datetime(
            cap_cutoff.year,
            cap_cutoff.month,
            cap_cutoff.day,
            tzinfo=UTC,
        )
        return cap_days, max(last_cutoff, cap_cutoff_dt)
    return cap_days, max(last_cutoff, cap_cutoff)


def since_display_date(since: date | datetime) -> date:
    """Extract plain ``date`` from a ``since`` cutoff for user-facing messages."""
    return since.date() if type(since) is datetime else since


def _resolve_article_window(
    date_from: date | datetime | None,
    settings: Settings,
    all_articles: bool,
    max_days: int | None,
) -> tuple[int, date | datetime]:
    """Compute ``(lookback_days, since_date)`` respecting an explicit ``--from``.

    When *date_from* is set the lookback window is extended to cover the
    requested date.  Otherwise falls through to ``_compute_article_window``.
    """
    if date_from is not None:
        from_date = date_from.date() if type(date_from) is datetime else date_from
        today = datetime.now(tz=UTC).date()
        cap_days = max((today - from_date).days + 1, 1)
        return cap_days, date_from
    return _compute_article_window(settings, all_articles, max_days)


def _effective_to(
    date_from: date | datetime | None,
    date_to: date | datetime | None,
) -> date | datetime | None:
    """Resolve the effective upper bound for article filtering.

    - ``date_to`` set → use it directly.
    - ``date_from`` set but ``date_to`` omitted → default to now.
    - Neither set → ``None`` (no upper-bound filtering).
    """
    if date_to is not None:
        return date_to
    if date_from is not None:
        return datetime.now(tz=UTC)
    return None


def _filter_articles_before(
    articles: list[DigestArticle],
    date_to: date | datetime,
) -> list[DigestArticle]:
    """Return articles published on or before *date_to*.

    - ``date`` (date-only): includes the entire day (strict ``<`` next-day midnight).
    - ``datetime``: includes articles up to and including the exact instant (``<=``).
    """
    if type(date_to) is date:
        cutoff = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(
            days=1,
        )
        return [a for a in articles if datetime.fromisoformat(a.published_at) < cutoff]
    return [a for a in articles if datetime.fromisoformat(a.published_at) <= date_to]


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    run_date: date,
    articles: list[DigestArticle],
    preferences: UserPreferences,
    routing_defaults: RoutingDefaults,
    agent_override: str | None,
    data_dir: str,
    coverage_start: str | None = None,
    coverage_end: str | None = None,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
    dedup_threshold: float = 0.90,
    dedup_model_name: str = "intfloat/multilingual-e5-small",
    use_api_key: bool = False,
    selection_params: dict[str, object] | None = None,
) -> None:
    """Serialize all pipeline inputs to ``pipeline_input.json`` in *pipeline_dir*."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "run_date": run_date.isoformat(),
        "articles": [msgspec.structs.asdict(a) for a in articles],
        "preferences": msgspec.structs.asdict(preferences),
        "routing_defaults": msgspec.structs.asdict(routing_defaults),
        "agent_override": agent_override,
        "data_dir": data_dir,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "min_resource_chars": min_resource_chars,
        "dedup_threshold": dedup_threshold,
        "dedup_model_name": dedup_model_name,
        "use_api_key": use_api_key,
    }
    if selection_params is not None:
        payload["selection_params"] = selection_params
    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        "utf-8",
    )
