"""CLI controller for recap pipeline commands."""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from news_recap.config import Settings, configure_prefect_runtime, resolve_prefect_mode
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.recap.prefect_flow import recap_flow
from news_recap.recap.resource_loader import ResourceLoader
from news_recap.recap.runner import (
    PipelineRunResult,
    UserPreferences,
    build_routing_defaults,
)

logger = logging.getLogger(__name__)

_SENTINEL = object()


@dataclass(slots=True)
class RecapRunCommand:
    """Input for recap run CLI command."""

    db_path: Path | None = None
    business_date: date | None = None
    agent_override: str | None = None


class RecapCliController:
    """CLI controller for recap pipeline operations."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Execute the full recap pipeline, yielding real-time progress lines."""

        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()

        mode = resolve_prefect_mode()
        effective_mode = configure_prefect_runtime(mode)
        yield f"Prefect runtime: {effective_mode.value}"

        with _repository(settings) as repository:
            articles = repository.list_user_retrieval_articles(limit=2000)
            if not articles:
                yield "No articles found in database. Run ingestion first."
                return

            yield f"Found {len(articles)} articles for {business_date}"
            yield "Starting pipeline…"

            progress_q: queue.Queue[str | object] = queue.Queue()

            def _on_progress(msg: str) -> None:
                progress_q.put(msg)

            result_holder: list[PipelineRunResult] = []
            error_holder: list[Exception] = []

            def _run() -> None:
                try:
                    with ResourceLoader() as loader:
                        result_holder.append(
                            recap_flow(
                                business_date=business_date,
                                preferences=UserPreferences(),
                                articles=articles,
                                workdir_root=settings.orchestrator.workdir_root,
                                routing_defaults=routing_defaults,
                                resource_loader=loader,
                                agent_override=command.agent_override,
                                on_progress=_on_progress,
                            ),
                        )
                except Exception as exc:  # noqa: BLE001
                    error_holder.append(exc)
                finally:
                    progress_q.put(_SENTINEL)

            worker_thread = threading.Thread(target=_run, daemon=True)
            worker_thread.start()

            while True:
                item = progress_q.get()
                if item is _SENTINEL:
                    break
                yield str(item)

            worker_thread.join(timeout=10)

            if error_holder:
                yield f"Pipeline failed with error: {error_holder[0]}"
                return

            if result_holder:
                yield from _format_run_result(result_holder[0])


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
def _repository(settings: Settings) -> Iterator[OrchestratorRepository]:
    repository = OrchestratorRepository(
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
