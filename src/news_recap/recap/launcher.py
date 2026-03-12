"""Prepare inputs and launch the recap pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.flow import recap_flow
from news_recap.recap.models import Digest, UserPreferences
from news_recap.recap.pipeline_setup import (
    _DIGEST_FILENAME,
    _build_routing_defaults,
    _find_resumable_pipeline,
    _write_pipeline_input,
)
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecapRunCommand:
    """CLI parameters for a pipeline launch."""

    data_dir: Path | None = None
    business_date: date | None = None
    agent_override: str | None = None
    article_limit: int | None = None
    stop_after: str | None = None
    fresh: bool = False
    api_mode: bool = False


def _patch_agent_override(pipeline_dir: Path, agent: str) -> str | None:
    """Patch ``agent_override`` in an existing ``pipeline_input.json``.

    Returns the previous value (or ``None`` if unset).
    """
    path = pipeline_dir / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    old = raw.get("agent_override")
    raw["agent_override"] = agent.strip().lower()
    path.write_text(json.dumps(raw, ensure_ascii=False, default=str), "utf-8")
    return old


class RecapCliController:
    """Load articles, materialize pipeline inputs, and launch the recap flow."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Fetch articles from store, write pipeline_input.json, and run recap_flow."""

        settings = Settings.from_env(
            data_dir=command.data_dir,
            execution_backend="api" if command.api_mode else None,
        )
        routing_defaults = _build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        preferences = UserPreferences()

        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()

        resumable = None
        if not command.fresh:
            resumable = _find_resumable_pipeline(
                settings.orchestrator.workdir_root.resolve(),
                business_date,
                command.article_limit,
            )

        if resumable:
            pipeline_dir = resumable
            digest = load_msgspec(resumable / _DIGEST_FILENAME, Digest)
            yield (
                f"Resuming pipeline: {pipeline_dir.name} "
                f"({len(digest.completed_phases)} phase(s) done: "
                f"{', '.join(digest.completed_phases) or 'none'})"
            )
            if command.agent_override:
                new_agent = command.agent_override.strip().lower()
                old_agent = _patch_agent_override(pipeline_dir, new_agent)
                yield f"Agent override changed: {old_agent or 'default'} -> {new_agent}"
        else:
            fetch_limit = command.article_limit or 2000
            articles = store.list_retrieval_articles(
                lookback_days=settings.ingestion.digest_lookback_days,
                limit=fetch_limit,
            )
            if not articles:
                yield "No articles found. Run ingestion first."
                return

            limit_note = f" (limited to {fetch_limit})" if command.article_limit else ""
            yield f"Found {len(articles)} articles for {business_date}{limit_note}"

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
            )
            yield f"New pipeline: {pipeline_dir}"

        yield "Starting pipeline…"

        recap_flow(
            pipeline_dir=str(pipeline_dir),
            business_date=business_date.isoformat(),
            stop_after=command.stop_after,
        )
