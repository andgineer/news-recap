"""Prepare inputs and launch the recap pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import click
import msgspec

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.digest_info import _human_elapsed, _human_size
from news_recap.recap.flow import recap_flow
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.pipeline_setup import (
    _DIGEST_FILENAME,
    _aggregate_usage,
    _build_routing_defaults,
    _effective_to,
    _filter_articles_before,
    _find_digest_pipeline_dir,
    _resolve_article_window,
    _write_pipeline_input,
    gc_old_pipelines,
    since_display_date,
)
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)

PipelineLine = tuple[str, str]
"""(severity, message) pair emitted during pipeline setup.

Severity values follow the same vocabulary as ``ScheduleLine``:
``"ok"`` | ``"info"`` | ``"warn"`` | ``"log"``.
"""


@dataclass(slots=True)
class RecapRunCommand:
    """CLI parameters for a pipeline launch."""

    agent_override: str | None = None
    article_limit: int | None = None
    stop_after: str | None = None
    fresh: bool = False
    api_mode: bool = False
    use_api_key: bool = False
    from_digest: int | None = None
    max_days: int | None = None
    all_articles: bool = False
    date_from: date | datetime | None = None
    date_to: date | datetime | None = None


def _patch_pipeline_input(pipeline_dir: Path, **fields: object) -> dict:
    """Patch fields in an existing ``pipeline_input.json``.

    Returns the previous values for the patched fields.
    """
    path = pipeline_dir / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    previous = {k: raw.get(k) for k in fields}
    raw.update(fields)
    path.write_text(json.dumps(raw, ensure_ascii=False, default=str), "utf-8")
    return previous


def _load_from_pipeline(pipeline_dir: Path) -> tuple[date, list[DigestArticle]]:
    """Load business date and articles from an existing pipeline's ``pipeline_input.json``."""
    path = pipeline_dir / "pipeline_input.json"
    if not path.exists():
        raise FileNotFoundError(f"No pipeline_input.json in {pipeline_dir}")
    raw = json.loads(path.read_text("utf-8"))
    run_date = date.fromisoformat(raw["run_date"])
    articles = [msgspec.convert(a, DigestArticle) for a in raw["articles"]]
    return run_date, articles


def _apply_resume_patches(
    command: RecapRunCommand,
    pipeline_dir: Path,
) -> Iterator[PipelineLine]:
    """Patch overridable fields on a resumed pipeline and yield status messages."""
    patches: dict[str, object] = {}
    if command.agent_override:
        patches["agent_override"] = command.agent_override.strip().lower()
    if command.use_api_key:
        patches["use_api_key"] = True
    if patches:
        previous = _patch_pipeline_input(pipeline_dir, **patches)
        if "agent_override" in patches:
            prev = previous.get("agent_override") or "default"
            yield ("info", f"Agent override changed: {prev} -> {patches['agent_override']}")


def _emit_run_summary(pipeline_dir: Path) -> Iterator[PipelineLine]:
    """Yield a few summary lines after pipeline completion."""
    digest_path = pipeline_dir / _DIGEST_FILENAME
    if not digest_path.exists():
        return
    digest = load_msgspec(digest_path, Digest)
    if digest.status != "completed":
        return

    usage = _aggregate_usage(pipeline_dir)
    elapsed = _human_elapsed(usage.elapsed)
    prompts = _human_size(usage.prompt_bytes)
    output = _human_size(usage.output_bytes)
    tokens = f"  tokens={usage.tokens:,}" if usage.tokens else ""
    yield (
        "ok",
        f"Done: {len(digest.articles)} articles, "
        f"{elapsed}, prompts={prompts}, output={output}{tokens}",
    )
    yield ("log", f"Workdir: {pipeline_dir}")


def _serialize_bound(value: date | datetime | None) -> dict[str, str] | None:
    """Serialize a date/datetime bound for stable JSON equality in selection_params."""
    if value is None:
        return None
    if type(value) is datetime:
        return {"kind": "datetime", "value": value.isoformat()}
    return {"kind": "date", "value": value.isoformat()}


def _base_selection_params(
    *,
    from_digest: int | None,
    max_days: int | None,
    all_articles: bool,
    date_from: date | datetime | None,
    date_to: date | datetime | None,
) -> dict[str, object]:
    """Article-selection params shared by ``create`` and ``prompt``.

    Used by ``_find_matching_resumable`` to decide whether an existing
    incomplete pipeline can be resumed.  Runtime-only overrides
    (``agent_override``, ``use_api_key``) are intentionally excluded.
    """
    return {
        "from_digest": from_digest,
        "max_days": max_days,
        "all_articles": all_articles,
        "date_from": _serialize_bound(date_from),
        "date_to": _serialize_bound(date_to),
    }


def _selection_params_for_create(command: RecapRunCommand) -> dict[str, object]:
    """Selection params for ``create``, adding ``article_limit``."""
    params = _base_selection_params(
        from_digest=command.from_digest,
        max_days=command.max_days,
        all_articles=command.all_articles,
        date_from=command.date_from,
        date_to=command.date_to,
    )
    params["article_limit"] = command.article_limit
    return params


def _validate_date_filters(
    date_from: date | datetime | None,
    date_to: date | datetime | None,
    from_digest: int | None,
    max_days: int | None,
    all_articles: bool,
) -> None:
    """Raise ``click.UsageError`` for incompatible flag combinations."""
    has_date = date_from is not None or date_to is not None
    if not has_date:
        return

    if from_digest is not None:
        raise click.UsageError("--from/--to cannot be combined with --from-digest.")
    if max_days is not None:
        raise click.UsageError("--from/--to cannot be combined with --max-days.")
    if all_articles:
        raise click.UsageError("--from/--to cannot be combined with --all.")

    if date_from is not None and date_to is not None:
        from_utc = (
            datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
            if type(date_from) is date
            else date_from
        )
        to_utc_exclusive = (
            datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)
            if type(date_to) is date
            else date_to
        )
        if from_utc >= to_utc_exclusive:
            raise click.UsageError("--from must be before --to.")


def _read_stored_selection_params(pdir: Path) -> dict[str, object] | None:
    """Read ``selection_params`` from ``pipeline_input.json`` in *pdir*, or ``None``."""
    pi_path = pdir / "pipeline_input.json"
    if not pi_path.exists():
        return None
    try:
        raw = json.loads(pi_path.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    sp = raw.get("selection_params")
    return sp if isinstance(sp, dict) else None


def _find_matching_resumable(
    workdir_root: Path,
    max_days: int,
    selection_params: dict[str, object],
) -> Path | None:
    """Find the latest incomplete pipeline whose selection params match.

    Scans newest-first within the lookback window.  Skips completed
    pipelines and legacy pipelines that lack ``selection_params``.
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
            continue

        stored = _read_stored_selection_params(pdir)
        if stored is None:
            continue
        if stored == selection_params:
            return pdir

    return None


def _load_fresh_articles(
    command: RecapRunCommand,
    settings: Settings,
    store: IngestionStore,
) -> tuple[list[DigestArticle], str | None, PipelineLine]:
    """Load articles from ingestion store, applying ``--from``/``--to`` filters."""
    cap_days, since_date = _resolve_article_window(
        command.date_from,
        settings,
        command.all_articles,
        command.max_days,
    )

    coverage_start = (
        since_date.isoformat()
        if isinstance(since_date, datetime)
        else datetime(since_date.year, since_date.month, since_date.day, tzinfo=UTC).isoformat()
    )

    fetch_limit = command.article_limit or 2000
    articles = store.list_retrieval_articles(
        lookback_days=cap_days,
        limit=fetch_limit,
        since=since_date,
    )

    upper = _effective_to(command.date_from, command.date_to)
    if upper is not None:
        articles = _filter_articles_before(articles, upper)

    limit_note = f" (limited to {fetch_limit})" if command.article_limit else ""
    info: PipelineLine = (
        "info",
        f"Found {len(articles)} articles since"
        f" {since_display_date(since_date)}"
        f" (cap {cap_days}d){limit_note}",
    )
    return articles, coverage_start, info


class RecapCliController:
    """Load articles, materialize pipeline inputs, and launch the recap flow."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[PipelineLine]:  # noqa: C901
        """Fetch articles from store, write pipeline_input.json, and run recap_flow."""
        _validate_date_filters(
            command.date_from,
            command.date_to,
            command.from_digest,
            command.max_days,
            command.all_articles,
        )

        settings = Settings.from_env(
            execution_backend="api" if command.api_mode else None,
        )
        routing_defaults = _build_routing_defaults(settings)
        preferences = UserPreferences()
        cap_days, _ = _resolve_article_window(
            command.date_from,
            settings,
            command.all_articles,
            command.max_days,
        )

        workdir_root = settings.orchestrator.workdir_root.resolve()

        source_articles: tuple[date, list[DigestArticle]] | None = None
        if command.from_digest is not None:
            source_dir = _find_digest_pipeline_dir(workdir_root, command.from_digest)
            if source_dir is None:
                raise click.ClickException(
                    f"Digest #{command.from_digest} not found. "
                    "Use `news-recap list` to see available digests.",
                )
            source_articles = _load_from_pipeline(source_dir)

        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()
        deleted = gc_old_pipelines(workdir_root, keep_days=settings.ingestion.gc_retention_days)
        if deleted:
            yield ("log", f"Auto-GC: removed {len(deleted)} old pipeline(s).")

        sel_params = _selection_params_for_create(command)

        resumable = None
        if not command.fresh and not source_articles:
            resumable = _find_matching_resumable(workdir_root, cap_days, sel_params)

        if resumable:
            pipeline_dir = resumable
            digest = load_msgspec(resumable / _DIGEST_FILENAME, Digest)
            run_date = date.fromisoformat(digest.run_date)
            yield (
                "info",
                f"Resuming pipeline: {pipeline_dir.name} "
                f"({len(digest.completed_phases)} phase(s) done: "
                f"{', '.join(digest.completed_phases) or 'none'})",
            )
            yield from _apply_resume_patches(command, pipeline_dir)
        else:
            run_date = source_articles[0] if source_articles else datetime.now(tz=UTC).date()

            articles: list[DigestArticle]
            coverage_start: str | None = None
            if source_articles:
                articles = source_articles[1]
                yield (
                    "info",
                    f"Reusing {len(articles)} from digest #{command.from_digest} ({run_date})",
                )
            else:
                articles, coverage_start, info_line = _load_fresh_articles(
                    command,
                    settings,
                    store,
                )
                if not articles:
                    yield ("warn", "No articles found. Run ingestion first.")
                    return
                yield info_line

            ts = datetime.now(tz=UTC).strftime("%H%M%S")
            pipeline_dir = (
                settings.orchestrator.workdir_root / f"pipeline-{run_date}-{ts}"
            ).resolve()
            _write_pipeline_input(
                pipeline_dir,
                run_date=run_date,
                articles=articles,
                preferences=preferences,
                routing_defaults=routing_defaults,
                agent_override=command.agent_override,
                data_dir=str(settings.data_dir),
                coverage_start=coverage_start,
                min_resource_chars=settings.ingestion.min_resource_chars,
                dedup_threshold=settings.dedup.threshold,
                dedup_model_name=settings.dedup.model_name,
                use_api_key=command.use_api_key,
                selection_params=sel_params,
            )
            yield ("log", f"New pipeline: {pipeline_dir}")

        yield ("ok", "Starting pipeline…")

        recap_flow(
            pipeline_dir=str(pipeline_dir),
            run_date=run_date.isoformat(),
            stop_after=command.stop_after,
        )

        yield from _emit_run_summary(pipeline_dir)
