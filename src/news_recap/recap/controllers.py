"""CLI controller for recap pipeline commands."""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from news_recap.config import Settings
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.recap.resource_loader import ResourceLoader
from news_recap.recap.runner import (
    PipelineRunResult,
    RecapPipelineRunner,
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


@dataclass(slots=True)
class RecapStatusCommand:
    """Input for recap status CLI command."""

    db_path: Path | None = None
    pipeline_id: str | None = None


@dataclass(slots=True)
class RecapTaskListCommand:
    """Input for recap task list CLI command."""

    db_path: Path | None = None


@dataclass(slots=True)
class RecapTaskKillCommand:
    """Input for recap task kill CLI command."""

    db_path: Path | None = None
    task_id: str | None = None
    force: bool = False


class RecapCliController:
    """CLI controller for recap pipeline operations."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Execute the full recap pipeline, yielding real-time progress lines."""

        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()

        with _repository(settings) as repository:
            articles = repository.list_user_retrieval_articles(limit=2000)
            if not articles:
                yield "No articles found in database. Run ingestion first."
                return

            yield f"Found {len(articles)} articles for {business_date}"
            yield "Starting pipeline (embedded worker will process LLM tasks)…"

            progress_q: queue.Queue[str | object] = queue.Queue()

            def _on_progress(msg: str) -> None:
                progress_q.put(msg)

            result_holder: list[PipelineRunResult] = []
            error_holder: list[Exception] = []

            def _run() -> None:
                try:
                    with ResourceLoader() as loader:
                        runner = RecapPipelineRunner(
                            repository=repository,
                            workdir_root=settings.orchestrator.workdir_root,
                            routing_defaults=routing_defaults,
                            resource_loader=loader,
                            embedded_worker=True,
                            on_progress=_on_progress,
                        )
                        result_holder.append(
                            runner.run(
                                business_date=business_date,
                                preferences=UserPreferences(),
                                articles=articles,
                                agent_override=command.agent_override,
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

    def pipeline_status(self, command: RecapStatusCommand) -> Iterator[str]:
        """Show status of a pipeline run."""

        settings = Settings.from_env(db_path=command.db_path)

        with _repository(settings) as repository:
            yield from _query_pipeline_status(repository, command.pipeline_id)

    def list_tasks(self, command: RecapTaskListCommand) -> Iterator[str]:
        """List tasks for the current (or latest) pipeline run."""

        settings = Settings.from_env(db_path=command.db_path)
        yield from _query_pipeline_tasks(settings)

    def kill_tasks(self, command: RecapTaskKillCommand) -> Iterator[str]:
        """Cancel tasks by id or all active tasks with --force."""

        settings = Settings.from_env(db_path=command.db_path)

        if command.task_id and command.force:
            yield "Error: specify either a task id or --force, not both."
            return

        if not command.task_id and not command.force:
            yield "Error: specify a task id or use --force to cancel all."
            return

        with _repository(settings) as repository:
            if command.task_id:
                try:
                    repository.cancel_task(task_id=command.task_id)
                    yield f"Canceled task {command.task_id}"
                except Exception as exc:  # noqa: BLE001
                    yield f"Failed to cancel task: {exc}"
                return

            yield from _force_kill_all(repository)


def _query_pipeline_status(
    repository: OrchestratorRepository,
    pipeline_id: str | None,
) -> Iterator[str]:
    """Query pipeline run status from the database."""

    conn = sqlite3.connect(str(repository.db_path))
    conn.row_factory = sqlite3.Row
    try:
        if pipeline_id:
            row = conn.execute(
                "SELECT * FROM recap_pipeline_runs WHERE pipeline_id = ?",
                (pipeline_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM recap_pipeline_runs"
                " ORDER BY (status = 'running') DESC, created_at DESC LIMIT 1",
            ).fetchone()

        if not row:
            yield "No pipeline runs found."
            return

        yield f"Pipeline {row['pipeline_id']}"
        yield f"  User:    {row['user_id']}"
        yield f"  Date:    {row['business_date']}"
        yield f"  Status:  {row['status']}"
        yield f"  Step:    {row['current_step'] or '—'}"
        yield f"  Started: {row['created_at']}"
        if row["error"]:
            yield f"  Error:   {row['error']}"

        tasks = conn.execute(
            "SELECT * FROM recap_pipeline_tasks WHERE pipeline_id = ? ORDER BY created_at",
            (row["pipeline_id"],),
        ).fetchall()
        if tasks:
            yield ""
            yield "  Steps:"
            for t in tasks:
                marker = "ok" if t["status"] == "completed" else t["status"]
                tid = t["task_id"][:12] if t["task_id"] else "—"
                yield f"    [{marker}] {t['step_name']}  task={tid}"
    finally:
        conn.close()


def _query_pipeline_tasks(settings: Settings) -> Iterator[str]:
    """List tasks for the active or latest pipeline run."""

    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        run_row = conn.execute(
            "SELECT pipeline_id, status, business_date"
            " FROM recap_pipeline_runs"
            " ORDER BY (status = 'running') DESC, created_at DESC LIMIT 1",
        ).fetchone()
        if not run_row:
            yield "No pipeline runs found."
            return

        yield (
            f"Pipeline {run_row['pipeline_id']}  "
            f"status={run_row['status']}  date={run_row['business_date']}"
        )

        rows = conn.execute(
            "SELECT pt.step_name, pt.task_id, pt.status AS step_status,"
            "       t.status AS task_status, t.attempt, t.max_attempts,"
            "       t.created_at, t.finished_at"
            " FROM recap_pipeline_tasks pt"
            " LEFT JOIN llm_tasks t ON pt.task_id = t.task_id"
            " WHERE pt.pipeline_id = ?"
            " ORDER BY pt.created_at",
            (run_row["pipeline_id"],),
        ).fetchall()

        if not rows:
            yield "  No tasks yet."
            return

        yield ""
        for r in rows:
            tid = r["task_id"][:12] if r["task_id"] else "—"
            status = r["task_status"] or r["step_status"]
            attempt = f"{r['attempt']}/{r['max_attempts']}" if r["attempt"] is not None else "—"
            yield f"  {r['step_name']:20s}  {tid}  status={status}  attempt={attempt}"
    finally:
        conn.close()


def _force_kill_all(repository: OrchestratorRepository) -> Iterator[str]:
    """Cancel all running/queued tasks and mark the active pipeline canceled."""

    conn = sqlite3.connect(str(repository.db_path))
    conn.row_factory = sqlite3.Row
    try:
        run_row = conn.execute(
            "SELECT pipeline_id FROM recap_pipeline_runs"
            " WHERE status = 'running'"
            " ORDER BY created_at DESC LIMIT 1",
        ).fetchone()

        task_ids = conn.execute(
            "SELECT task_id FROM llm_tasks"
            " WHERE status IN ('queued', 'running')"
            " ORDER BY created_at",
        ).fetchall()
    finally:
        conn.close()

    canceled = 0
    for row in task_ids:
        try:
            repository.cancel_task(task_id=row["task_id"])
            yield f"  Canceled task {row['task_id'][:12]}"
            canceled += 1
        except Exception:  # noqa: BLE001
            logger.debug("Could not cancel task %s", row["task_id"], exc_info=True)

    if run_row:
        now = datetime.now(tz=UTC).isoformat()
        conn2 = sqlite3.connect(str(repository.db_path))
        try:
            conn2.execute(
                "UPDATE recap_pipeline_runs"
                " SET status = 'canceled', error = 'Force-killed by user', updated_at = ?"
                " WHERE pipeline_id = ?",
                (now, run_row["pipeline_id"]),
            )
            conn2.commit()
        finally:
            conn2.close()
        yield f"  Pipeline {run_row['pipeline_id'][:12]} marked canceled."

    yield f"Done: {canceled} task(s) canceled."


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
