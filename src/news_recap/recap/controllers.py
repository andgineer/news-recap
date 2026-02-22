"""CLI controller for recap pipeline commands."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from news_recap.config import Settings, configure_prefect_runtime, resolve_prefect_mode
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.recap.prefect_flow import recap_flow
from news_recap.recap.runner import (
    PipelineRunResult,
    UserPreferences,
    build_routing_defaults,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecapRunCommand:
    """Input for recap run CLI command."""

    db_path: Path | None = None
    business_date: date | None = None
    agent_override: str | None = None
    article_limit: int | None = None
    classify_only: bool = False


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    business_date: date,
    articles: list,
    preferences: UserPreferences,
    routing_defaults: object,
    agent_override: str | None,
) -> None:
    """Serialize all pipeline inputs to ``pipeline_input.json`` in *pipeline_dir*."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "business_date": business_date.isoformat(),
        "articles": [a.to_dict() for a in articles],
        "preferences": preferences.to_dict(),
        "routing_defaults": routing_defaults.to_dict(),  # type: ignore[union-attr]
        "agent_override": agent_override,
    }
    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        "utf-8",
    )


class RecapCliController:
    """CLI controller for recap pipeline operations."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Execute the full recap pipeline, yielding status lines."""

        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        preferences = UserPreferences()

        mode = resolve_prefect_mode()
        effective_mode = configure_prefect_runtime(mode)
        yield f"Prefect runtime: {effective_mode.value}"

        with _repository(settings) as repository:
            fetch_limit = command.article_limit or 2000
            articles = repository.list_user_retrieval_articles(limit=fetch_limit)
            if not articles:
                yield "No articles found in database. Run ingestion first."
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

            result = recap_flow(
                pipeline_dir=str(pipeline_dir),
                business_date=business_date.isoformat(),
                classify_only=command.classify_only,
            )
            yield from _format_run_result(result)


def _format_run_result(result: PipelineRunResult) -> Iterator[str]:
    yield ""
    yield f"Pipeline {result.pipeline_id}"
    yield f"  Date: {result.business_date}"
    yield f"  Status: {result.status}"

    for step in result.steps:
        status_marker = "ok" if step.status == "completed" else step.status
        task_info = f" (task {step.task_id[:12]})" if step.task_id else ""
        yield f"  [{status_marker}] {step.step_name}{task_info}"
        if step.error:
            yield f"    Error: {step.error}"

    if result.error:
        yield f"  Error: {result.error}"

    if result.digest:
        yield ""
        yield "Digest preview:"
        yield json.dumps(result.digest, ensure_ascii=False, indent=2)[:3000]


@contextmanager
def _repository(settings: Settings) -> Iterator[SQLiteRepository]:
    repository = SQLiteRepository(
        db_path=settings.db_path,
        user_id=settings.user_context.user_id,
        user_name=settings.user_context.user_name,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    repository.init_schema()
    try:
        yield repository
    finally:
        repository.close()
