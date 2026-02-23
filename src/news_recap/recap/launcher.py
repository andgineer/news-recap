"""Prepare inputs and launch the recap Prefect pipeline."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import msgspec

from news_recap.config import Settings, configure_prefect_runtime, resolve_prefect_mode
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.flow import recap_flow
from news_recap.recap.models import DigestArticle
from news_recap.recap.routing import RoutingDefaults
from news_recap.recap.runner import (
    UserPreferences,
    build_routing_defaults,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecapRunCommand:
    """CLI parameters for a pipeline launch."""

    data_dir: Path | None = None
    business_date: date | None = None
    agent_override: str | None = None
    article_limit: int | None = None
    stop_after: str | None = None


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    business_date: date,
    articles: list[DigestArticle],
    preferences: UserPreferences,
    routing_defaults: RoutingDefaults,
    agent_override: str | None,
) -> None:
    """Serialize all pipeline inputs to ``pipeline_input.json`` in *pipeline_dir*."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "business_date": business_date.isoformat(),
        "articles": [msgspec.structs.asdict(a) for a in articles],
        "preferences": msgspec.structs.asdict(preferences),
        "routing_defaults": msgspec.structs.asdict(routing_defaults),
        "agent_override": agent_override,
    }
    import json

    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        "utf-8",
    )


class RecapCliController:
    """Load articles, materialize pipeline inputs, and launch the Prefect flow."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Fetch articles from store, write pipeline_input.json, and run recap_flow."""

        settings = Settings.from_env(data_dir=command.data_dir)
        routing_defaults = build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        preferences = UserPreferences()

        mode = resolve_prefect_mode()
        effective_mode = configure_prefect_runtime(mode)
        yield f"Prefect runtime: {effective_mode.value}"

        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()

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
        )
        yield f"Pipeline dir: {pipeline_dir}"
        yield "Starting pipeline…"

        recap_flow(
            pipeline_dir=str(pipeline_dir),
            business_date=business_date.isoformat(),
            stop_after=command.stop_after,
        )
