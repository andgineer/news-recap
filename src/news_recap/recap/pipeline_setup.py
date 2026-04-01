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
    """Pre-computed metadata for a completed digest, stored in the index."""

    digest_id: int
    pipeline_dir_name: str
    business_date: str
    article_count: int
    earliest_article: str | None = None
    latest_article: str | None = None
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


def _find_resumable_pipeline(
    workdir_root: Path,
    max_days: int,
    article_limit: int | None,
) -> Path | None:
    """Find the latest incomplete pipeline created within the last *max_days* days.

    Pipelines are scanned newest-first.  The search stops as soon as a
    completed pipeline is found (anything older is already covered).
    Returns ``None`` when no resumable candidate exists or the candidate
    was created with a different article limit.
    """
    if not workdir_root.is_dir():
        return None

    cutoff = datetime.now(tz=UTC).date() - timedelta(days=max_days)

    candidates: list[Path] = sorted(
        (p for p in workdir_root.iterdir() if p.is_dir() and p.name.startswith("pipeline-")),
        key=lambda p: p.name,
        reverse=True,
    )

    for pdir in candidates:
        try:
            dir_date = date.fromisoformat(pdir.name.split("-", 1)[1].rsplit("-", 1)[0])
        except (ValueError, IndexError):
            continue
        if dir_date < cutoff:
            break

        digest_path = pdir / _DIGEST_FILENAME
        if not digest_path.exists():
            continue
        try:
            digest = load_msgspec(digest_path, Digest)
        except Exception:  # noqa: BLE001
            logger.debug("Cannot read digest in %s, skipping", pdir.name)
            continue

        if digest.status == "completed":
            break

        if article_limit and len(digest.articles) != article_limit:
            logger.info(
                "Skipping %s: article count mismatch (%d vs requested %d)",
                pdir.name,
                len(digest.articles),
                article_limit,
            )
            continue

        return pdir

    return None


@dataclass(slots=True)
class DigestSummary:
    """Metadata for a single completed digest."""

    digest_id: int
    business_date: date
    article_count: int
    earliest_article: datetime | None
    latest_article: datetime | None
    pipeline_dir_name: str
    started_at: datetime | None = None
    elapsed_seconds: float = 0.0
    total_tokens: int = 0
    prompt_bytes: int = 0
    output_bytes: int = 0


def _find_last_completed_digest_date(workdir_root: Path) -> date | None:
    """Return the business_date of the most recent fully completed digest, or ``None``."""
    entries = _load_digest_index(workdir_root)
    if not entries:
        return None
    newest = max(entries, key=lambda e: e.pipeline_dir_name)
    return date.fromisoformat(newest.business_date)


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


def register_digest(workdir_root: Path, pdir: Path, digest: Digest) -> None:
    """Register a completed digest in the index.

    No-op when the digest does not qualify (wrong status / missing phase)
    or when it is already registered (idempotent).
    """
    if digest.status != "completed" or "oneshot_digest" not in digest.completed_phases:
        return

    entries = _load_digest_index(workdir_root)
    dir_name = pdir.name
    if any(e.pipeline_dir_name == dir_name for e in entries):
        return

    timestamps: list[datetime] = []
    for article in digest.articles:
        try:
            timestamps.append(datetime.fromisoformat(article.published_at))
        except (ValueError, TypeError):
            continue

    usage = _aggregate_usage(pdir)
    started = _parse_pipeline_start(dir_name)

    entry = DigestIndexEntry(
        digest_id=_next_free_id(entries),
        pipeline_dir_name=dir_name,
        business_date=digest.business_date,
        article_count=len(digest.articles),
        earliest_article=min(timestamps).isoformat() if timestamps else None,
        latest_article=max(timestamps).isoformat() if timestamps else None,
        started_at=started.isoformat() if started else None,
        elapsed_seconds=usage.elapsed,
        total_tokens=usage.tokens,
        prompt_bytes=usage.prompt_bytes,
        output_bytes=usage.output_bytes,
    )
    entries.append(entry)
    _save_digest_index(workdir_root, entries)
    logger.info("Registered digest #%d (%s)", entry.digest_id, dir_name)


def unregister_digest(workdir_root: Path, digest_id: int) -> str | None:
    """Remove a digest from the index. Returns the ``pipeline_dir_name`` or ``None``."""
    entries = _load_digest_index(workdir_root)
    for i, e in enumerate(entries):
        if e.digest_id == digest_id:
            removed = entries.pop(i)
            _save_digest_index(workdir_root, entries)
            return removed.pipeline_dir_name
    return None


def _list_completed_digests(workdir_root: Path) -> list[DigestSummary]:
    """Return metadata for all completed digests, newest-first."""
    entries = _load_digest_index(workdir_root)
    newest_first = sorted(entries, key=lambda e: e.pipeline_dir_name, reverse=True)
    return [
        DigestSummary(
            digest_id=e.digest_id,
            business_date=date.fromisoformat(e.business_date),
            article_count=e.article_count,
            earliest_article=(
                datetime.fromisoformat(e.earliest_article) if e.earliest_article else None
            ),
            latest_article=(datetime.fromisoformat(e.latest_article) if e.latest_article else None),
            pipeline_dir_name=e.pipeline_dir_name,
            started_at=datetime.fromisoformat(e.started_at) if e.started_at else None,
            elapsed_seconds=e.elapsed_seconds,
            total_tokens=e.total_tokens,
            prompt_bytes=e.prompt_bytes,
            output_bytes=e.output_bytes,
        )
        for e in newest_first
    ]


def _find_digest_pipeline_dir(workdir_root: Path, digest_id: int) -> Path | None:
    """Return the pipeline directory for the given stable *digest_id*."""
    for e in _load_digest_index(workdir_root):
        if e.digest_id == digest_id:
            return workdir_root / e.pipeline_dir_name
    return None


def _find_latest_digest_pipeline_dir(workdir_root: Path) -> Path | None:
    """Return the pipeline directory of the newest completed digest."""
    entries = _load_digest_index(workdir_root)
    if not entries:
        return None
    newest = max(entries, key=lambda e: e.pipeline_dir_name)
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
) -> tuple[int, date]:
    """Return ``(lookback_days, since_date)`` for article retrieval.

    By default articles are loaded since the last completed digest,
    capped at *max_days* (or ``settings.ingestion.digest_lookback_days``).
    When *all_articles* is ``True`` the last-digest anchor is skipped
    and only the cap applies.
    """
    cap_days = max_days or settings.ingestion.digest_lookback_days
    today = datetime.now(tz=UTC).date()
    cap_cutoff = today - timedelta(days=cap_days)

    last_digest_date: date | None = None
    if not all_articles:
        last_digest_date = _find_last_completed_digest_date(
            settings.orchestrator.workdir_root.resolve(),
        )

    since = max(last_digest_date, cap_cutoff) if last_digest_date else cap_cutoff
    return cap_days, since


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    business_date: date,
    articles: list[DigestArticle],
    preferences: UserPreferences,
    routing_defaults: RoutingDefaults,
    agent_override: str | None,
    data_dir: str,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
    dedup_threshold: float = 0.90,
    dedup_model_name: str = "intfloat/multilingual-e5-small",
    use_api_key: bool = False,
) -> None:
    """Serialize all pipeline inputs to ``pipeline_input.json`` in *pipeline_dir*."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "business_date": business_date.isoformat(),
        "articles": [msgspec.structs.asdict(a) for a in articles],
        "preferences": msgspec.structs.asdict(preferences),
        "routing_defaults": msgspec.structs.asdict(routing_defaults),
        "agent_override": agent_override,
        "data_dir": data_dir,
        "min_resource_chars": min_resource_chars,
        "dedup_threshold": dedup_threshold,
        "dedup_model_name": dedup_model_name,
        "use_api_key": use_api_key,
    }
    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        "utf-8",
    )
