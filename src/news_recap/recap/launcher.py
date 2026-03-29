"""Prepare inputs and launch the recap pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import msgspec

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.flow import recap_flow
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.pipeline_setup import (
    _DIGEST_FILENAME,
    _build_routing_defaults,
    _compute_article_window,
    _find_resumable_pipeline,
    _write_pipeline_input,
)
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecapRunCommand:
    """CLI parameters for a pipeline launch."""

    agent_override: str | None = None
    article_limit: int | None = None
    stop_after: str | None = None
    fresh: bool = False
    api_mode: bool = False
    use_api_key: bool = False
    from_pipeline: Path | None = None
    max_days: int | None = None
    all_articles: bool = False


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
    business_date = date.fromisoformat(raw["business_date"])
    articles = [msgspec.convert(a, DigestArticle) for a in raw["articles"]]
    return business_date, articles


def _apply_resume_patches(
    command: RecapRunCommand,
    pipeline_dir: Path,
) -> Iterator[str]:
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
            yield f"Agent override changed: {prev} -> {patches['agent_override']}"


class RecapCliController:
    """Load articles, materialize pipeline inputs, and launch the recap flow."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Fetch articles from store, write pipeline_input.json, and run recap_flow."""

        settings = Settings.from_env(
            execution_backend="api" if command.api_mode else None,
        )
        routing_defaults = _build_routing_defaults(settings)
        preferences = UserPreferences()
        cap_days = command.max_days or settings.ingestion.digest_lookback_days

        source_articles: tuple[date, list[DigestArticle]] | None = None
        if command.from_pipeline:
            source_articles = _load_from_pipeline(command.from_pipeline)

        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()

        resumable = None
        if not command.fresh and not source_articles:
            resumable = _find_resumable_pipeline(
                settings.orchestrator.workdir_root.resolve(),
                cap_days,
                command.article_limit,
            )

        if resumable:
            pipeline_dir = resumable
            digest = load_msgspec(resumable / _DIGEST_FILENAME, Digest)
            business_date = date.fromisoformat(digest.business_date)
            yield (
                f"Resuming pipeline: {pipeline_dir.name} "
                f"({len(digest.completed_phases)} phase(s) done: "
                f"{', '.join(digest.completed_phases) or 'none'})"
            )
            yield from _apply_resume_patches(command, pipeline_dir)
        else:
            business_date = source_articles[0] if source_articles else datetime.now(tz=UTC).date()

            articles: list[DigestArticle]
            if source_articles:
                articles = source_articles[1]
                yield (
                    f"Reusing {len(articles)} articles from "
                    f"{command.from_pipeline.name} ({business_date})"  # type: ignore[union-attr]
                )
            else:
                fetch_limit = command.article_limit or 2000
                _cap_days, since_date = _compute_article_window(
                    settings,
                    command.all_articles,
                    command.max_days,
                )
                articles = store.list_retrieval_articles(
                    lookback_days=_cap_days,
                    limit=fetch_limit,
                    since=since_date,
                )
                if not articles:
                    yield "No articles found. Run ingestion first."
                    return
                limit_note = f" (limited to {fetch_limit})" if command.article_limit else ""
                yield (
                    f"Found {len(articles)} articles since {since_date}"
                    f" (cap {_cap_days}d){limit_note}"
                )

            ts = datetime.now(tz=UTC).strftime("%H%M%S")
            pipeline_dir = (
                settings.orchestrator.workdir_root / f"pipeline-{business_date}-{ts}"
            ).resolve()
            _write_pipeline_input(
                pipeline_dir,
                business_date=business_date,
                articles=articles,
                preferences=preferences,
                routing_defaults=routing_defaults,
                agent_override=command.agent_override,
                data_dir=str(settings.data_dir),
                min_resource_chars=settings.ingestion.min_resource_chars,
                dedup_threshold=settings.dedup.threshold,
                dedup_model_name=settings.dedup.model_name,
                use_api_key=command.use_api_key,
            )
            yield f"New pipeline: {pipeline_dir}"

        yield "Starting pipeline…"

        recap_flow(
            pipeline_dir=str(pipeline_dir),
            business_date=business_date.isoformat(),
            stop_after=command.stop_after,
        )
