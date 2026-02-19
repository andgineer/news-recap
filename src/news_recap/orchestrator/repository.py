"""Persistent queue repository for orchestrator tasks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlalchemy import update as sa_update
from sqlmodel import Session, col, delete, select

from news_recap.ingestion.storage.alembic_runner import upgrade_head
from news_recap.ingestion.storage.common import (
    build_sqlite_engine,
    connect_sqlite_with_policy,
    utc_now,
)
from news_recap.ingestion.storage.sqlmodel_models import (
    DEFAULT_USER_ID,
    AppUser,
    Article,
    DailyStorySnapshot,
    LlmTask,
    LlmTaskArtifact,
    LlmTaskAttempt,
    LlmTaskEvent,
    MonitorQuestion,
    OutputCitationSnapshot,
    OutputFeedback,
    ReadStateEvent,
    StoryAssignment,
    UserArticle,
    UserOutput,
    UserOutputBlock,
    UserStoryDefinition,
)
from news_recap.orchestrator.models import (
    DailyStorySnapshotView,
    DailyStorySnapshotWrite,
    FailureClass,
    LlmCostAggregateView,
    LlmTaskArtifactWrite,
    LlmTaskAttemptFinish,
    LlmTaskAttemptStart,
    LlmTaskAttemptView,
    LlmTaskCreate,
    LlmTaskDetails,
    LlmTaskEventView,
    LlmTaskStatus,
    LlmTaskView,
    MonitorQuestionView,
    MonitorQuestionWrite,
    OutputCitationSnapshotView,
    OutputCitationSnapshotWrite,
    OutputFeedbackWrite,
    ReadStateEventWrite,
    SourceCorpusEntry,
    StoryAssignmentView,
    StoryAssignmentWrite,
    StoryDefinitionView,
    StoryDefinitionWrite,
    UserOutputBlockWrite,
    UserOutputUpsert,
    UserOutputView,
)


class OrchestratorRepository:
    """Queue persistence facade backed by SQLModel + SQLite."""

    def __init__(
        self,
        db_path: Path,
        *,
        user_id: str = DEFAULT_USER_ID,
        user_name: str = "Default User",
        sqlite_busy_timeout_ms: int = 5_000,
    ) -> None:
        self.db_path = db_path
        self.user_id = user_id
        self.user_name = user_name
        self.sqlite_busy_timeout_ms = sqlite_busy_timeout_ms

        # Intentional trade-off: this repository owns its own SQLAlchemy engine
        # even when other repositories target the same SQLite file.
        # Operational consistency is enforced via shared SQLite policy
        # (WAL + busy_timeout + foreign_keys), which is sufficient for the
        # current single-machine CLI deployment while keeping repository
        # construction independent.
        self.engine = build_sqlite_engine(
            db_path=db_path,
            busy_timeout_ms=sqlite_busy_timeout_ms,
        )

        self._connection = connect_sqlite_with_policy(
            db_path=db_path,
            busy_timeout_ms=sqlite_busy_timeout_ms,
        )

    def close(self) -> None:
        """Close underlying DB resources."""

        self._connection.close()
        self.engine.dispose()

    def init_schema(self) -> None:
        """Run schema migrations and ensure actor context exists."""

        upgrade_head(self.db_path)
        self._ensure_actor_context()

    def _ensure_actor_context(self) -> None:
        with Session(self.engine) as session:
            user = session.exec(
                select(AppUser).where(AppUser.user_id == self.user_id),
            ).one_or_none()
            if user is not None:
                return
            session.add(
                AppUser(
                    user_id=self.user_id,
                    display_name=self.user_name,
                    created_at=utc_now(),
                ),
            )
            session.commit()

    def enqueue_task(self, payload: LlmTaskCreate) -> LlmTaskView:
        """Create a queued task."""

        now = utc_now()
        task_id = payload.task_id or str(uuid4())
        with Session(self.engine) as session:
            row = LlmTask(
                task_id=task_id,
                user_id=self.user_id,
                task_type=payload.task_type,
                priority=payload.priority,
                status=LlmTaskStatus.QUEUED.value,
                attempt=0,
                max_attempts=payload.max_attempts,
                timeout_seconds=payload.timeout_seconds,
                run_after=_to_db_datetime(payload.run_after or now),
                input_manifest_path=payload.input_manifest_path,
                output_path=payload.output_path,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            self._add_event(
                session=session,
                task_id=task_id,
                event_type="enqueued",
                status_from=None,
                status_to=LlmTaskStatus.QUEUED,
                details={
                    "task_type": payload.task_type,
                    "priority": payload.priority,
                    "max_attempts": payload.max_attempts,
                    "timeout_seconds": payload.timeout_seconds,
                },
            )
            session.commit()
            session.refresh(row)
            return _to_task_view(row)

    def claim_next_ready_task(self, *, worker_id: str) -> LlmTaskView | None:
        """Atomically claim one task ready for execution."""

        while True:
            now = utc_now()
            with Session(self.engine) as session:
                candidate = session.exec(
                    select(LlmTask)
                    .where(
                        LlmTask.user_id == self.user_id,
                        LlmTask.status == LlmTaskStatus.QUEUED.value,
                        LlmTask.run_after <= _to_db_datetime(now),
                    )
                    .order_by(
                        col(LlmTask.priority).asc(),
                        col(LlmTask.run_after).asc(),
                        col(LlmTask.created_at).asc(),
                    )
                    .limit(1),
                ).one_or_none()
                if candidate is None:
                    return None

                result = session.exec(
                    sa_update(LlmTask)
                    .where(
                        col(LlmTask.task_id) == candidate.task_id,
                        col(LlmTask.user_id) == self.user_id,
                        col(LlmTask.status) == LlmTaskStatus.QUEUED.value,
                    )
                    .values(
                        status=LlmTaskStatus.RUNNING.value,
                        attempt=candidate.attempt + 1,
                        started_at=_to_db_datetime(now),
                        heartbeat_at=_to_db_datetime(now),
                        finished_at=None,
                        failure_class=None,
                        error_summary=None,
                        last_exit_code=None,
                        worker_id=worker_id,
                        updated_at=_to_db_datetime(now),
                    ),
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue

                claimed = session.exec(
                    select(LlmTask).where(LlmTask.task_id == candidate.task_id),
                ).one()
                self._add_event(
                    session=session,
                    task_id=claimed.task_id,
                    event_type="claimed",
                    status_from=LlmTaskStatus.QUEUED,
                    status_to=LlmTaskStatus.RUNNING,
                    details={"worker_id": worker_id, "attempt": claimed.attempt},
                )
                session.commit()
                return _to_task_view(claimed)

    def recover_stale_running_tasks(
        self,
        *,
        stale_after: timedelta,
        limit: int = 100,
    ) -> int:
        """Recover stale running tasks using timeout+grace policy with CAS guard."""

        if stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be > 0")

        now = utc_now()
        recovered = 0
        with Session(self.engine) as session:
            # NOTE: stale filtering is intentionally done in Python after loading
            # the oldest RUNNING rows (up to `limit`), not in SQL. This keeps the
            # query simple for the current low-concurrency deployment.
            # In a future multi-worker/high-cardinality setup, move stale
            # predicate logic into SQL WHERE to avoid potential starvation for
            # stale rows beyond this limited scan window.
            running_rows = session.exec(
                select(LlmTask)
                .where(
                    LlmTask.user_id == self.user_id,
                    LlmTask.status == LlmTaskStatus.RUNNING.value,
                )
                .order_by(col(LlmTask.started_at).asc())
                .limit(limit),
            ).all()

            for row in running_rows:
                started_at = row.started_at or row.updated_at or row.created_at
                stale_deadline = (
                    _to_utc_aware_datetime(started_at)
                    + timedelta(
                        seconds=int(row.timeout_seconds),
                    )
                    + stale_after
                )
                if now <= stale_deadline:
                    continue

                predicates = [
                    col(LlmTask.task_id) == row.task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == LlmTaskStatus.RUNNING.value,
                    col(LlmTask.started_at) == row.started_at,
                ]
                if row.worker_id is None:
                    predicates.append(col(LlmTask.worker_id).is_(None))
                else:
                    predicates.append(col(LlmTask.worker_id) == row.worker_id)

                result = session.exec(
                    sa_update(LlmTask)
                    .where(*predicates)
                    .values(
                        status=LlmTaskStatus.QUEUED.value,
                        run_after=_to_db_datetime(now),
                        started_at=None,
                        heartbeat_at=None,
                        finished_at=None,
                        failure_class=None,
                        error_summary=None,
                        last_exit_code=None,
                        repair_attempted_at=None,
                        worker_id=None,
                        updated_at=_to_db_datetime(now),
                    ),
                )
                if result.rowcount != 1:
                    continue

                self._add_event(
                    session=session,
                    task_id=row.task_id,
                    event_type="stale_recovered",
                    status_from=LlmTaskStatus.RUNNING,
                    status_to=LlmTaskStatus.QUEUED,
                    details={
                        "observed_worker_id": row.worker_id,
                        "observed_started_at": _to_utc_aware_datetime(started_at).isoformat(),
                        "stale_after_seconds": int(stale_after.total_seconds()),
                    },
                )
                recovered += 1

            session.commit()
        return recovered

    def touch_task(self, *, task_id: str) -> None:
        """Update heartbeat for a running task."""

        now = utc_now()
        with Session(self.engine) as session:
            row = session.exec(
                select(LlmTask).where(
                    LlmTask.task_id == task_id,
                    LlmTask.user_id == self.user_id,
                    LlmTask.status == LlmTaskStatus.RUNNING.value,
                ),
            ).one_or_none()
            if row is None:
                return
            row.heartbeat_at = _to_db_datetime(now)
            row.updated_at = _to_db_datetime(now)
            session.add(row)
            session.commit()

    def mark_repair_attempted(self, *, task_id: str) -> bool:
        """Record one in-attempt repair pass."""

        now = utc_now()
        with Session(self.engine) as session:
            result = session.exec(
                sa_update(LlmTask)
                .where(
                    col(LlmTask.task_id) == task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == LlmTaskStatus.RUNNING.value,
                )
                .values(
                    repair_attempted_at=_to_db_datetime(now),
                    updated_at=_to_db_datetime(now),
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            self._add_event(
                session=session,
                task_id=task_id,
                event_type="repair_attempted",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.RUNNING,
                details={},
            )
            session.commit()
            return True

    def complete_task(
        self,
        *,
        task_id: str,
        output_path: str,
        citations: list[OutputCitationSnapshotWrite] | None = None,
        user_output: UserOutputUpsert | None = None,
    ) -> bool:
        """Mark a running task as succeeded."""

        now = utc_now()
        with Session(self.engine) as session:
            result = session.exec(
                sa_update(LlmTask)
                .where(
                    col(LlmTask.task_id) == task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == LlmTaskStatus.RUNNING.value,
                )
                .values(
                    status=LlmTaskStatus.SUCCEEDED.value,
                    finished_at=_to_db_datetime(now),
                    heartbeat_at=_to_db_datetime(now),
                    output_path=output_path,
                    updated_at=_to_db_datetime(now),
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                return False

            if citations is not None:
                session.exec(
                    delete(OutputCitationSnapshot).where(
                        col(OutputCitationSnapshot.task_id) == task_id,
                        col(OutputCitationSnapshot.user_id) == self.user_id,
                    ),
                )
                for citation in citations:
                    session.add(
                        OutputCitationSnapshot(
                            user_id=self.user_id,
                            task_id=task_id,
                            source_id=citation.source_id,
                            article_id=citation.article_id,
                            title=citation.title,
                            url=citation.url,
                            source=citation.source,
                            published_at=(
                                _to_db_datetime(citation.published_at)
                                if citation.published_at is not None
                                else None
                            ),
                            created_at=now,
                        ),
                    )

            if user_output is not None:
                self._upsert_user_output_in_session(
                    session=session,
                    payload=UserOutputUpsert(
                        kind=user_output.kind,
                        business_date=user_output.business_date,
                        status=user_output.status,
                        payload=user_output.payload,
                        blocks=user_output.blocks,
                        story_id=user_output.story_id,
                        monitor_id=user_output.monitor_id,
                        request_id=user_output.request_id,
                        task_id=task_id,
                        title=user_output.title,
                    ),
                )

            self._add_event(
                session=session,
                task_id=task_id,
                event_type="succeeded",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.SUCCEEDED,
                details={
                    "output_path": output_path,
                    "citation_count": len(citations or []),
                    "output_persisted": user_output is not None,
                },
            )
            session.commit()
            return True

    def fail_task(  # noqa: PLR0913
        self,
        *,
        task_id: str,
        status: LlmTaskStatus,
        failure_class: FailureClass,
        error_summary: str,
        last_exit_code: int | None,
        details: dict[str, object] | None = None,
    ) -> bool:
        """Mark a running task as failed/timeout."""

        now = utc_now()
        if status not in {LlmTaskStatus.FAILED, LlmTaskStatus.TIMEOUT}:
            raise ValueError(f"Unsupported failure status: {status}")

        with Session(self.engine) as session:
            result = session.exec(
                sa_update(LlmTask)
                .where(
                    col(LlmTask.task_id) == task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == LlmTaskStatus.RUNNING.value,
                )
                .values(
                    status=status.value,
                    failure_class=failure_class.value,
                    error_summary=error_summary,
                    last_exit_code=last_exit_code,
                    finished_at=_to_db_datetime(now),
                    heartbeat_at=_to_db_datetime(now),
                    updated_at=_to_db_datetime(now),
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            self._add_event(
                session=session,
                task_id=task_id,
                event_type="failed",
                status_from=LlmTaskStatus.RUNNING,
                status_to=status,
                details={
                    "failure_class": failure_class.value,
                    "last_exit_code": last_exit_code,
                    "error_summary": error_summary,
                    **(details or {}),
                },
            )
            session.commit()
            return True

    def schedule_retry(  # noqa: PLR0913
        self,
        *,
        task_id: str,
        run_after: datetime,
        timeout_seconds: int,
        failure_class: FailureClass,
        error_summary: str,
        last_exit_code: int | None,
        details: dict[str, object] | None = None,
    ) -> bool:
        """Requeue a running task for automatic retry."""

        now = utc_now()
        with Session(self.engine) as session:
            result = session.exec(
                sa_update(LlmTask)
                .where(
                    col(LlmTask.task_id) == task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == LlmTaskStatus.RUNNING.value,
                )
                .values(
                    status=LlmTaskStatus.QUEUED.value,
                    run_after=_to_db_datetime(run_after),
                    timeout_seconds=timeout_seconds,
                    failure_class=failure_class.value,
                    error_summary=error_summary,
                    last_exit_code=last_exit_code,
                    started_at=None,
                    finished_at=None,
                    heartbeat_at=None,
                    worker_id=None,
                    repair_attempted_at=None,
                    updated_at=_to_db_datetime(now),
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            self._add_event(
                session=session,
                task_id=task_id,
                event_type="retry_scheduled",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.QUEUED,
                details={
                    "run_after": _to_utc_aware_datetime(run_after).isoformat(),
                    "timeout_seconds": timeout_seconds,
                    "failure_class": failure_class.value,
                    **(details or {}),
                },
            )
            session.commit()
            return True

    def add_task_event(
        self,
        *,
        task_id: str,
        event_type: str,
        details: dict[str, object] | None = None,
        status_from: LlmTaskStatus | None = None,
        status_to: LlmTaskStatus | None = None,
    ) -> None:
        """Append custom task event with optional details."""

        with Session(self.engine) as session:
            row = session.exec(
                select(LlmTask).where(
                    LlmTask.task_id == task_id,
                    LlmTask.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                raise RuntimeError(f"Task not found: {task_id}")
            self._add_event(
                session=session,
                task_id=task_id,
                event_type=event_type,
                status_from=status_from,
                status_to=status_to,
                details=details or {},
            )
            session.commit()

    def retry_task(self, *, task_id: str) -> None:
        """Manual operator retry for failed/timeout tasks."""

        now = utc_now()
        with Session(self.engine) as session:
            row = session.exec(
                select(LlmTask).where(
                    LlmTask.task_id == task_id,
                    LlmTask.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                raise RuntimeError(f"Task not found: {task_id}")

            previous = LlmTaskStatus(row.status)
            if previous not in {
                LlmTaskStatus.FAILED,
                LlmTaskStatus.TIMEOUT,
                LlmTaskStatus.CANCELED,
            }:
                raise RuntimeError(
                    "Only failed/timeout/canceled tasks can be retried manually, "
                    f"got {row.status}.",
                )
            result = session.exec(
                sa_update(LlmTask)
                .where(
                    col(LlmTask.task_id) == task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == previous.value,
                )
                .values(
                    status=LlmTaskStatus.QUEUED.value,
                    run_after=_to_db_datetime(now),
                    finished_at=None,
                    started_at=None,
                    heartbeat_at=None,
                    failure_class=None,
                    error_summary=None,
                    last_exit_code=None,
                    repair_attempted_at=None,
                    worker_id=None,
                    updated_at=_to_db_datetime(now),
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                raise RuntimeError(
                    "Task state changed concurrently while retrying; "
                    f"please retry command (task_id={task_id}).",
                )

            self._add_event(
                session=session,
                task_id=task_id,
                event_type="manual_retry",
                status_from=previous,
                status_to=LlmTaskStatus.QUEUED,
                details={},
            )
            session.commit()

    def cancel_task(self, *, task_id: str) -> None:
        """Cancel a queued/running task."""

        now = utc_now()
        with Session(self.engine) as session:
            row = session.exec(
                select(LlmTask).where(
                    LlmTask.task_id == task_id,
                    LlmTask.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                raise RuntimeError(f"Task not found: {task_id}")

            previous = LlmTaskStatus(row.status)
            if previous not in {LlmTaskStatus.QUEUED, LlmTaskStatus.RUNNING}:
                raise RuntimeError(f"Task cannot be canceled from status={row.status}")

            result = session.exec(
                sa_update(LlmTask)
                .where(
                    col(LlmTask.task_id) == task_id,
                    col(LlmTask.user_id) == self.user_id,
                    col(LlmTask.status) == previous.value,
                )
                .values(
                    status=LlmTaskStatus.CANCELED.value,
                    finished_at=_to_db_datetime(now),
                    heartbeat_at=_to_db_datetime(now),
                    updated_at=_to_db_datetime(now),
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                raise RuntimeError(
                    "Task state changed concurrently while canceling; "
                    f"please retry command (task_id={task_id}).",
                )

            self._add_event(
                session=session,
                task_id=task_id,
                event_type="canceled",
                status_from=previous,
                status_to=LlmTaskStatus.CANCELED,
                details={},
            )
            session.commit()

    def list_tasks(
        self,
        *,
        status: LlmTaskStatus | None = None,
        limit: int = 50,
    ) -> list[LlmTaskView]:
        """List recent tasks, optionally filtered by status."""

        with Session(self.engine) as session:
            statement = (
                select(LlmTask)
                .where(LlmTask.user_id == self.user_id)
                .order_by(col(LlmTask.created_at).desc())
                .limit(limit)
            )
            if status is not None:
                statement = statement.where(LlmTask.status == status.value)
            rows = session.exec(statement).all()
        return [_to_task_view(row) for row in rows]

    def list_tasks_for_metrics(
        self,
        *,
        since: datetime | None = None,
        task_ids: tuple[str, ...] | None = None,
        statuses: tuple[LlmTaskStatus, ...] | None = None,
    ) -> list[LlmTaskView]:
        """List tasks for metrics/reporting use-cases."""

        with Session(self.engine) as session:
            statement = select(LlmTask).where(LlmTask.user_id == self.user_id)
            if since is not None:
                cutoff = _to_db_datetime(since)
                statement = statement.where(
                    or_(
                        col(LlmTask.finished_at) >= cutoff,
                        and_(
                            col(LlmTask.finished_at).is_(None),
                            col(LlmTask.updated_at) >= cutoff,
                        ),
                    ),
                )
            if task_ids:
                statement = statement.where(col(LlmTask.task_id).in_(task_ids))
            if statuses:
                statement = statement.where(
                    col(LlmTask.status).in_(tuple(status.value for status in statuses)),
                )
            rows = session.exec(statement).all()
        return [_to_task_view(row) for row in rows]

    def list_task_events_for_metrics(
        self,
        *,
        since: datetime | None = None,
        task_ids: tuple[str, ...] | None = None,
        event_types: tuple[str, ...] | None = None,
    ) -> list[LlmTaskEventView]:
        """List task events for metrics/reporting use-cases."""

        with Session(self.engine) as session:
            statement = (
                select(LlmTaskEvent)
                .where(
                    LlmTaskEvent.user_id == self.user_id,
                )
                .order_by(col(LlmTaskEvent.created_at).asc())
            )
            if since is not None:
                statement = statement.where(
                    LlmTaskEvent.created_at >= _to_db_datetime(since),
                )
            if task_ids:
                statement = statement.where(col(LlmTaskEvent.task_id).in_(task_ids))
            if event_types:
                statement = statement.where(col(LlmTaskEvent.event_type).in_(event_types))
            rows = session.exec(statement).all()
        return [_to_task_event_view(row) for row in rows]

    def get_task_details(self, *, task_id: str) -> LlmTaskDetails | None:
        """Return task details with event stream."""

        with Session(self.engine) as session:
            task = session.exec(
                select(LlmTask).where(
                    LlmTask.task_id == task_id,
                    LlmTask.user_id == self.user_id,
                ),
            ).one_or_none()
            if task is None:
                return None

            event_rows = session.exec(
                select(LlmTaskEvent)
                .where(
                    LlmTaskEvent.task_id == task_id,
                    LlmTaskEvent.user_id == self.user_id,
                )
                .order_by(col(LlmTaskEvent.created_at).asc()),
            ).all()
        return LlmTaskDetails(
            task=_to_task_view(task),
            events=[_to_task_event_view(row) for row in event_rows],
        )

    def add_artifact(self, *, task_id: str, artifact: LlmTaskArtifactWrite) -> None:
        """Persist artifact metadata."""

        with Session(self.engine) as session:
            row = LlmTaskArtifact(
                task_id=task_id,
                user_id=self.user_id,
                kind=artifact.kind,
                path=artifact.path,
                size_bytes=artifact.size_bytes,
                checksum_sha256=artifact.checksum_sha256,
                created_at=utc_now(),
            )
            session.add(row)
            session.commit()

    def upsert_task_attempt_start(self, payload: LlmTaskAttemptStart) -> None:
        """Create or refresh running attempt telemetry row."""

        now = utc_now()
        with Session(self.engine) as session:
            row = session.exec(
                select(LlmTaskAttempt).where(
                    col(LlmTaskAttempt.user_id) == self.user_id,
                    col(LlmTaskAttempt.task_id) == payload.task_id,
                    col(LlmTaskAttempt.attempt_no) == payload.attempt_no,
                ),
            ).one_or_none()
            if row is None:
                row = LlmTaskAttempt(
                    task_id=payload.task_id,
                    user_id=self.user_id,
                    attempt_no=payload.attempt_no,
                    task_type=payload.task_type,
                    status=payload.status,
                    started_at=_to_db_datetime(payload.started_at),
                    finished_at=None,
                    duration_ms=None,
                    worker_id=payload.worker_id,
                    agent=payload.agent,
                    model=payload.model,
                    profile=payload.profile,
                    command_template_hash=payload.command_template_hash,
                    timed_out=False,
                    created_at=now,
                )
            else:
                row.task_type = payload.task_type
                row.status = payload.status
                row.started_at = _to_db_datetime(payload.started_at)
                row.finished_at = None
                row.duration_ms = None
                row.worker_id = payload.worker_id
                row.agent = payload.agent
                row.model = payload.model
                row.profile = payload.profile
                row.command_template_hash = payload.command_template_hash
                row.timed_out = False
            session.add(row)
            session.commit()

    def finalize_task_attempt(self, payload: LlmTaskAttemptFinish) -> None:
        """Finalize telemetry row for one attempt."""

        with Session(self.engine) as session:
            row = session.exec(
                select(LlmTaskAttempt).where(
                    col(LlmTaskAttempt.user_id) == self.user_id,
                    col(LlmTaskAttempt.task_id) == payload.task_id,
                    col(LlmTaskAttempt.attempt_no) == payload.attempt_no,
                ),
            ).one_or_none()
            if row is None:
                task = session.exec(
                    select(LlmTask).where(
                        col(LlmTask.user_id) == self.user_id,
                        col(LlmTask.task_id) == payload.task_id,
                    ),
                ).one_or_none()
                if task is None:
                    raise RuntimeError(f"Task not found: {payload.task_id}")
                fallback_started_at = payload.started_at
                if fallback_started_at is None and task.started_at is not None:
                    fallback_started_at = _to_utc_aware_datetime(task.started_at)
                if fallback_started_at is None:
                    fallback_started_at = payload.finished_at
                row = LlmTaskAttempt(
                    task_id=payload.task_id,
                    user_id=self.user_id,
                    attempt_no=payload.attempt_no,
                    task_type=task.task_type,
                    status=payload.status,
                    started_at=_to_db_datetime(fallback_started_at),
                    created_at=utc_now(),
                )

            finished_at_db = _to_db_datetime(payload.finished_at)
            started_utc = _to_utc_aware_datetime(row.started_at)
            duration_ms = max(
                0,
                int(
                    (_to_utc_aware_datetime(payload.finished_at) - started_utc).total_seconds()
                    * 1000,
                ),
            )

            row.status = payload.status
            row.finished_at = finished_at_db
            row.duration_ms = duration_ms
            row.exit_code = payload.exit_code
            row.timed_out = payload.timed_out
            row.failure_class = (
                payload.failure_class.value if payload.failure_class is not None else None
            )
            row.attempt_failure_code = payload.attempt_failure_code
            row.error_summary_sanitized = payload.error_summary_sanitized
            row.stdout_preview_sanitized = payload.stdout_preview_sanitized
            row.stderr_preview_sanitized = payload.stderr_preview_sanitized
            row.output_chars = payload.output_chars
            row.prompt_tokens = payload.prompt_tokens
            row.completion_tokens = payload.completion_tokens
            row.total_tokens = payload.total_tokens
            row.usage_status = payload.usage_status
            row.usage_source = payload.usage_source
            row.usage_parser_version = payload.usage_parser_version
            row.estimated_cost_usd = payload.estimated_cost_usd
            session.add(row)
            session.commit()

    def list_task_attempts(self, *, task_id: str) -> list[LlmTaskAttemptView]:
        """List attempts for one task ordered by attempt number."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(LlmTaskAttempt)
                .where(
                    col(LlmTaskAttempt.user_id) == self.user_id,
                    col(LlmTaskAttempt.task_id) == task_id,
                )
                .order_by(col(LlmTaskAttempt.attempt_no).asc()),
            ).all()
        return [_to_task_attempt_view(row) for row in rows]

    def list_attempt_failures(  # noqa: PLR0913
        self,
        *,
        since: datetime,
        task_type: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        failure_class: FailureClass | None = None,
        limit: int = 50,
    ) -> list[LlmTaskAttemptView]:
        """List failed attempts with deterministic ordering and filters."""

        with Session(self.engine) as session:
            statement = (
                select(LlmTaskAttempt)
                .where(
                    col(LlmTaskAttempt.user_id) == self.user_id,
                    col(LlmTaskAttempt.created_at) >= _to_db_datetime(since),
                    col(LlmTaskAttempt.status).in_(("failed", "timeout")),
                )
                .order_by(
                    func.coalesce(  # type: ignore[arg-type]
                        col(LlmTaskAttempt.finished_at),
                        col(LlmTaskAttempt.started_at),
                        col(LlmTaskAttempt.created_at),
                    ).desc(),
                    col(LlmTaskAttempt.task_id).asc(),
                    col(LlmTaskAttempt.attempt_no).desc(),
                )
                .limit(max(1, limit))
            )
            if task_type is not None:
                statement = statement.where(col(LlmTaskAttempt.task_type) == task_type)
            if agent is not None:
                statement = statement.where(col(LlmTaskAttempt.agent) == agent)
            if model is not None:
                statement = statement.where(col(LlmTaskAttempt.model) == model)
            if failure_class is not None:
                statement = statement.where(
                    col(LlmTaskAttempt.failure_class) == failure_class.value,
                )
            rows = session.exec(statement).all()
        return [_to_task_attempt_view(row) for row in rows]

    def aggregate_attempt_costs(
        self,
        *,
        since: datetime,
        group_by: str,
    ) -> list[LlmCostAggregateView]:
        """Aggregate attempt usage/cost metrics."""

        attempts = self._list_attempts_for_window(since=since)
        grouped: dict[str, LlmCostAggregateView] = {}

        for attempt in attempts:
            if group_by == "agent":
                group_key = attempt.agent or "-"
            elif group_by == "task_type":
                group_key = attempt.task_type
            else:
                group_key = attempt.model or "-"

            bucket = grouped.setdefault(
                group_key,
                LlmCostAggregateView(
                    group_key=group_key,
                    attempts=0,
                    succeeded=0,
                    failed=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    estimated_cost_usd=0.0,
                    unknown_usage=0,
                ),
            )
            bucket.attempts += 1
            if attempt.status == "succeeded":
                bucket.succeeded += 1
            if attempt.status in {"failed", "timeout"}:
                bucket.failed += 1
            bucket.prompt_tokens += int(attempt.prompt_tokens or 0)
            bucket.completion_tokens += int(attempt.completion_tokens or 0)
            bucket.total_tokens += int(attempt.total_tokens or 0)
            bucket.estimated_cost_usd += float(attempt.estimated_cost_usd or 0.0)
            if attempt.usage_status != "reported":
                bucket.unknown_usage += 1

        return sorted(grouped.values(), key=lambda item: item.group_key)

    def _list_attempts_for_window(self, *, since: datetime) -> list[LlmTaskAttemptView]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(LlmTaskAttempt)
                .where(
                    col(LlmTaskAttempt.user_id) == self.user_id,
                    col(LlmTaskAttempt.created_at) >= _to_db_datetime(since),
                )
                .order_by(col(LlmTaskAttempt.created_at).desc()),
            ).all()
        return [_to_task_attempt_view(row) for row in rows]

    def list_user_retrieval_articles(
        self,
        *,
        limit: int = 20,
        since: datetime | None = None,
        until: datetime | None = None,
        source_ids: tuple[str, ...] | None = None,
    ) -> list[SourceCorpusEntry]:
        """Resolve user-scoped retrieval corpus entries from `user_articles`."""

        with Session(self.engine) as session:
            if source_ids is None:
                statement = (
                    select(Article, UserArticle)
                    .join(
                        UserArticle,
                        col(UserArticle.article_id) == col(Article.article_id),
                    )
                    .where(UserArticle.user_id == self.user_id)
                )
                if since is not None:
                    statement = statement.where(
                        UserArticle.discovered_at >= _to_db_datetime(since),
                    )
                if until is not None:
                    statement = statement.where(
                        UserArticle.discovered_at < _to_db_datetime(until),
                    )
                rows = session.exec(
                    statement.order_by(col(UserArticle.discovered_at).desc()).limit(max(1, limit)),
                ).all()
                return [
                    SourceCorpusEntry(
                        source_id=f"article:{article.article_id}",
                        article_id=article.article_id,
                        title=article.title,
                        url=article.url,
                        source=article.source_domain,
                        published_at=_to_utc_aware_datetime(article.published_at),
                    )
                    for article, _user_link in rows
                ]

            normalized_source_ids = tuple(dict.fromkeys(source_ids))
            article_ids: list[str] = []
            for source_id in normalized_source_ids:
                article_id = _article_id_from_source_id(source_id)
                if article_id is None:
                    raise ValueError(
                        f"Invalid source_id format: {source_id!r}. "
                        "Expected 'article:<article_id>'.",
                    )
                article_ids.append(article_id)

            rows = session.exec(
                select(Article)
                .join(
                    UserArticle,
                    col(UserArticle.article_id) == col(Article.article_id),
                )
                .where(
                    UserArticle.user_id == self.user_id,
                    col(Article.article_id).in_(article_ids),
                ),
            ).all()
            by_article_id = {row.article_id: row for row in rows}
            resolved: list[SourceCorpusEntry] = []
            for source_id in normalized_source_ids:
                article_id = _article_id_from_source_id(source_id)
                if article_id is None:
                    continue
                article = by_article_id.get(article_id)
                if article is None:
                    continue
                resolved.append(
                    SourceCorpusEntry(
                        source_id=f"article:{article.article_id}",
                        article_id=article.article_id,
                        title=article.title,
                        url=article.url,
                        source=article.source_domain,
                        published_at=_to_utc_aware_datetime(article.published_at),
                    ),
                )
            return resolved

    def upsert_story_definition(self, payload: StoryDefinitionWrite) -> StoryDefinitionView:
        """Create or update pinned story definition."""

        now = utc_now()
        story_id = payload.story_id or str(uuid4())
        with Session(self.engine) as session:
            row = session.exec(
                select(UserStoryDefinition).where(
                    UserStoryDefinition.story_id == story_id,
                    UserStoryDefinition.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                row = UserStoryDefinition(
                    story_id=story_id,
                    user_id=self.user_id,
                    name=payload.name,
                    description=payload.description,
                    target_language=payload.target_language,
                    priority=payload.priority,
                    enabled=payload.enabled,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.name = payload.name
                row.description = payload.description
                row.target_language = payload.target_language
                row.priority = payload.priority
                row.enabled = payload.enabled
                row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_story_definition_view(row)

    def list_story_definitions(
        self,
        *,
        include_disabled: bool = False,
    ) -> list[StoryDefinitionView]:
        """List user story definitions ordered by priority."""

        with Session(self.engine) as session:
            statement = (
                select(UserStoryDefinition)
                .where(col(UserStoryDefinition.user_id) == self.user_id)
                .order_by(
                    col(UserStoryDefinition.priority).asc(),
                    col(UserStoryDefinition.created_at).asc(),
                )
            )
            if not include_disabled:
                statement = statement.where(col(UserStoryDefinition.enabled).is_(True))
            rows = session.exec(statement).all()
            return [_to_story_definition_view(row) for row in rows]

    def upsert_monitor_question(self, payload: MonitorQuestionWrite) -> MonitorQuestionView:
        """Create or update monitor prompt definition."""

        now = utc_now()
        monitor_id = payload.monitor_id or str(uuid4())
        with Session(self.engine) as session:
            row = session.exec(
                select(MonitorQuestion).where(
                    MonitorQuestion.monitor_id == monitor_id,
                    MonitorQuestion.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                row = MonitorQuestion(
                    monitor_id=monitor_id,
                    user_id=self.user_id,
                    name=payload.name,
                    prompt=payload.prompt,
                    cadence=payload.cadence,
                    enabled=payload.enabled,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.name = payload.name
                row.prompt = payload.prompt
                row.cadence = payload.cadence
                row.enabled = payload.enabled
                row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_monitor_question_view(row)

    def list_monitor_questions(
        self,
        *,
        include_disabled: bool = False,
    ) -> list[MonitorQuestionView]:
        """List monitor prompts for current user."""

        with Session(self.engine) as session:
            statement = (
                select(MonitorQuestion)
                .where(col(MonitorQuestion.user_id) == self.user_id)
                .order_by(col(MonitorQuestion.created_at).asc())
            )
            if not include_disabled:
                statement = statement.where(col(MonitorQuestion.enabled).is_(True))
            rows = session.exec(statement).all()
            return [_to_monitor_question_view(row) for row in rows]

    def replace_story_assignments(
        self,
        *,
        business_date: date,
        assignments: list[StoryAssignmentWrite],
    ) -> int:
        """Replace full assignment set for one user/date (idempotent rerun)."""

        with Session(self.engine) as session:
            session.exec(
                delete(StoryAssignment).where(
                    col(StoryAssignment.user_id) == self.user_id,
                    col(StoryAssignment.business_date) == business_date,
                ),
            )
            for assignment in assignments:
                session.add(
                    StoryAssignment(
                        user_id=self.user_id,
                        business_date=assignment.business_date,
                        article_id=assignment.article_id,
                        story_id=assignment.story_id,
                        story_key=assignment.story_key,
                        assignment_type=assignment.assignment_type,
                        score=assignment.score,
                        created_at=utc_now(),
                    ),
                )
            session.commit()
            return len(assignments)

    def list_story_assignments(self, *, business_date: date) -> list[StoryAssignmentView]:
        """List assignments for one business date."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(StoryAssignment)
                .where(
                    StoryAssignment.user_id == self.user_id,
                    StoryAssignment.business_date == business_date,
                )
                .order_by(
                    col(StoryAssignment.story_key).asc(),
                    col(StoryAssignment.score).desc(),
                    col(StoryAssignment.article_id).asc(),
                ),
            ).all()
            return [
                StoryAssignmentView(
                    article_id=row.article_id,
                    story_id=row.story_id,
                    story_key=row.story_key,
                    assignment_type=row.assignment_type,
                    score=row.score,
                )
                for row in rows
            ]

    def replace_daily_story_snapshots(
        self,
        *,
        business_date: date,
        snapshots: list[DailyStorySnapshotWrite],
    ) -> int:
        """Replace full daily continuity snapshots for one date."""

        now = utc_now()
        with Session(self.engine) as session:
            session.exec(
                delete(DailyStorySnapshot).where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) == business_date,
                ),
            )
            for snapshot in snapshots:
                session.add(
                    DailyStorySnapshot(
                        user_id=self.user_id,
                        business_date=snapshot.business_date,
                        story_id=snapshot.story_id,
                        story_key=snapshot.story_key,
                        title=snapshot.title,
                        continuity_key=snapshot.continuity_key,
                        summary_json=json.dumps(
                            snapshot.summary,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        created_at=now,
                        updated_at=now,
                    ),
                )
            session.commit()
            return len(snapshots)

    def list_daily_story_snapshots(self, *, business_date: date) -> list[DailyStorySnapshotView]:
        """List persisted daily snapshots for one date."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(DailyStorySnapshot)
                .where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) == business_date,
                )
                .order_by(col(DailyStorySnapshot.story_key).asc()),
            ).all()
            return [_to_daily_story_snapshot_view(row) for row in rows]

    def get_latest_daily_story_snapshots_before(
        self,
        *,
        business_date: date,
    ) -> list[DailyStorySnapshotView]:
        """Return latest prior-day snapshot set for continuity context."""

        with Session(self.engine) as session:
            latest_date = session.exec(
                select(col(DailyStorySnapshot.business_date))
                .where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) < business_date,
                )
                .order_by(col(DailyStorySnapshot.business_date).desc())
                .limit(1),
            ).one_or_none()
            if latest_date is None:
                return []
            rows = session.exec(
                select(DailyStorySnapshot)
                .where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) == latest_date,
                )
                .order_by(col(DailyStorySnapshot.story_key).asc()),
            ).all()
            return [_to_daily_story_snapshot_view(row) for row in rows]

    def upsert_user_output(self, payload: UserOutputUpsert) -> UserOutputView:
        """Upsert stable business output row and replace its blocks."""

        with Session(self.engine) as session:
            row = self._upsert_user_output_in_session(session=session, payload=payload)
            session.commit()

            refreshed = session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.output_id) == row.output_id,
                ),
            ).one()
            block_rows = session.exec(
                select(UserOutputBlock)
                .where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(UserOutputBlock.output_id) == row.output_id,
                )
                .order_by(col(UserOutputBlock.block_order).asc()),
            ).all()
            return _to_user_output_view(refreshed, block_rows)

    def get_user_output(self, *, output_id: str) -> UserOutputView | None:
        """Fetch one output with ordered blocks."""

        with Session(self.engine) as session:
            row = session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.output_id) == output_id,
                ),
            ).one_or_none()
            if row is None:
                return None
            blocks = session.exec(
                select(UserOutputBlock)
                .where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(UserOutputBlock.output_id) == row.output_id,
                )
                .order_by(col(UserOutputBlock.block_order).asc()),
            ).all()
            return _to_user_output_view(row, blocks)

    def list_user_outputs(
        self,
        *,
        kind: str | None = None,
        business_date: date | None = None,
        limit: int = 50,
    ) -> list[UserOutputView]:
        """List recent outputs with blocks."""

        with Session(self.engine) as session:
            statement = (
                select(UserOutput)
                .where(col(UserOutput.user_id) == self.user_id)
                .order_by(col(UserOutput.updated_at).desc())
                .limit(max(1, limit))
            )
            if kind is not None:
                statement = statement.where(col(UserOutput.kind) == kind)
            if business_date is not None:
                statement = statement.where(col(UserOutput.business_date) == business_date)
            rows = session.exec(statement).all()
            if not rows:
                return []
            output_ids = [row.output_id for row in rows]
            block_rows = session.exec(
                select(UserOutputBlock).where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(UserOutputBlock.output_id).in_(output_ids),
                ),
            ).all()
            blocks_by_output: dict[str, list[UserOutputBlock]] = {}
            for block in block_rows:
                blocks_by_output.setdefault(block.output_id, []).append(block)
            for values in blocks_by_output.values():
                values.sort(key=lambda row: row.block_order)
            return [
                _to_user_output_view(row, blocks_by_output.get(row.output_id, [])) for row in rows
            ]

    def add_read_state_event(self, payload: ReadStateEventWrite) -> None:
        """Persist read/open event for output or output block."""

        with Session(self.engine) as session:
            self._ensure_user_output_exists(session=session, output_id=payload.output_id)
            if payload.output_block_id is not None:
                self._ensure_block_matches_output(
                    session=session,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                )
            session.add(
                ReadStateEvent(
                    user_id=self.user_id,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                    event_type=payload.event_type,
                    details_json=(
                        json.dumps(payload.details, ensure_ascii=False, sort_keys=True)
                        if payload.details
                        else None
                    ),
                    created_at=utc_now(),
                ),
            )
            session.commit()

    def add_output_feedback(self, payload: OutputFeedbackWrite) -> None:
        """Persist feedback against output or block."""

        with Session(self.engine) as session:
            self._ensure_user_output_exists(session=session, output_id=payload.output_id)
            if payload.output_block_id is not None:
                self._ensure_block_matches_output(
                    session=session,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                )
            session.add(
                OutputFeedback(
                    user_id=self.user_id,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                    feedback_type=payload.feedback_type,
                    value=payload.value,
                    details_json=(
                        json.dumps(payload.details, ensure_ascii=False, sort_keys=True)
                        if payload.details
                        else None
                    ),
                    created_at=utc_now(),
                ),
            )
            session.commit()

    def list_recent_read_source_ids(self, *, days: int = 3) -> set[str]:
        """Return source ids from output blocks that were marked as viewed/opened recently."""

        cutoff = _to_db_datetime(utc_now() - timedelta(days=max(1, days)))
        with Session(self.engine) as session:
            rows = session.exec(
                select(col(UserOutputBlock.source_ids_json))
                .join(
                    ReadStateEvent,
                    and_(
                        col(ReadStateEvent.user_id) == col(UserOutputBlock.user_id),
                        col(ReadStateEvent.output_id) == col(UserOutputBlock.output_id),
                        col(ReadStateEvent.output_block_id) == col(UserOutputBlock.block_id),
                    ),
                )
                .where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(ReadStateEvent.created_at) >= cutoff,
                    col(ReadStateEvent.output_block_id).is_not(None),
                    col(ReadStateEvent.event_type).in_(("open", "view", "expand")),
                ),
            ).all()

        source_ids: set[str] = set()
        for row in rows:
            source_ids_json = row if isinstance(row, str) else str(row)
            try:
                parsed = json.loads(source_ids_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                if isinstance(item, str) and item:
                    source_ids.add(item)
        return source_ids

    def intelligence_stats_snapshot(self, *, since: datetime) -> dict[str, int]:
        """Aggregate domain counters for observability windows."""

        since_date = _to_utc_aware_datetime(since).date().isoformat()
        since_dt = _to_utc_aware_datetime(since).replace(tzinfo=None).isoformat(sep=" ")

        queries = {
            "stories_total": (
                "SELECT COUNT(*) AS value FROM user_story_definitions WHERE user_id = ?",
                (self.user_id,),
            ),
            "stories_enabled": (
                "SELECT COUNT(*) AS value FROM user_story_definitions "
                "WHERE user_id = ? AND enabled = 1",
                (self.user_id,),
            ),
            "story_assignments_window": (
                "SELECT COUNT(*) AS value FROM story_assignments "
                "WHERE user_id = ? AND business_date >= ?",
                (self.user_id, since_date),
            ),
            "story_snapshots_window": (
                "SELECT COUNT(*) AS value FROM daily_story_snapshots "
                "WHERE user_id = ? AND business_date >= ?",
                (self.user_id, since_date),
            ),
            "outputs_window": (
                "SELECT COUNT(*) AS value FROM user_outputs WHERE user_id = ? AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_highlights_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'highlights' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_story_details_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'story_details' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_monitor_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'monitor_answer' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_qa_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'qa_answer' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "read_state_events_window": (
                "SELECT COUNT(*) AS value FROM read_state_events "
                "WHERE user_id = ? AND created_at >= ?",
                (self.user_id, since_dt),
            ),
            "feedback_events_window": (
                "SELECT COUNT(*) AS value FROM output_feedback "
                "WHERE user_id = ? AND created_at >= ?",
                (self.user_id, since_dt),
            ),
        }
        result: dict[str, int] = {}
        for key, (query, params) in queries.items():
            row = self._connection.execute(query, params).fetchone()
            result[key] = int(row["value"]) if row is not None else 0
        return result

    def validate_user_source_ids(
        self,
        *,
        source_ids: tuple[str, ...],
    ) -> tuple[list[SourceCorpusEntry], list[str]]:
        """Validate that source IDs belong to current user via `user_articles`."""

        normalized_source_ids = tuple(dict.fromkeys(source_ids))
        resolved = self.list_user_retrieval_articles(source_ids=normalized_source_ids)
        resolved_ids = {entry.source_id for entry in resolved}
        missing = [
            source_id for source_id in normalized_source_ids if source_id not in resolved_ids
        ]
        return resolved, missing

    def persist_output_citation_snapshots(
        self,
        *,
        task_id: str,
        citations: list[OutputCitationSnapshotWrite],
    ) -> int:
        """Persist immutable citation snapshots for a completed output."""

        with Session(self.engine) as session:
            task = session.exec(
                select(LlmTask).where(
                    LlmTask.task_id == task_id,
                    LlmTask.user_id == self.user_id,
                ),
            ).one_or_none()
            if task is None:
                raise RuntimeError(f"Task not found: {task_id}")

            session.exec(
                delete(OutputCitationSnapshot).where(
                    col(OutputCitationSnapshot.task_id) == task_id,
                    col(OutputCitationSnapshot.user_id) == self.user_id,
                ),
            )

            for citation in citations:
                session.add(
                    OutputCitationSnapshot(
                        user_id=self.user_id,
                        task_id=task_id,
                        source_id=citation.source_id,
                        article_id=citation.article_id,
                        title=citation.title,
                        url=citation.url,
                        source=citation.source,
                        published_at=(
                            _to_db_datetime(citation.published_at)
                            if citation.published_at is not None
                            else None
                        ),
                        created_at=utc_now(),
                    ),
                )
            session.commit()
            return len(citations)

    def list_output_citations(self, *, task_id: str) -> list[OutputCitationSnapshotView]:
        """List stored output citation snapshots for one task."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(OutputCitationSnapshot)
                .where(
                    OutputCitationSnapshot.task_id == task_id,
                    OutputCitationSnapshot.user_id == self.user_id,
                )
                .order_by(col(OutputCitationSnapshot.source_id).asc()),
            ).all()
        return [
            OutputCitationSnapshotView(
                id=row.id or 0,
                task_id=row.task_id,
                source_id=row.source_id,
                article_id=row.article_id,
                title=row.title,
                url=row.url,
                source=row.source,
                published_at=(
                    _to_utc_aware_datetime(row.published_at)
                    if row.published_at is not None
                    else None
                ),
                created_at=_to_utc_aware_datetime(row.created_at),
            )
            for row in rows
        ]

    def _resolve_existing_user_output(
        self,
        *,
        session: Session,
        payload: UserOutputUpsert,
    ) -> UserOutput | None:
        if payload.request_id is not None:
            return session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.kind) == payload.kind,
                    col(UserOutput.request_id) == payload.request_id,
                ),
            ).one_or_none()
        if payload.monitor_id is not None:
            return session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.kind) == payload.kind,
                    col(UserOutput.business_date) == payload.business_date,
                    col(UserOutput.monitor_id) == payload.monitor_id,
                ),
            ).one_or_none()
        if payload.story_id is not None:
            return session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.kind) == payload.kind,
                    col(UserOutput.business_date) == payload.business_date,
                    col(UserOutput.story_id) == payload.story_id,
                ),
            ).one_or_none()
        return session.exec(
            select(UserOutput).where(
                col(UserOutput.user_id) == self.user_id,
                col(UserOutput.kind) == payload.kind,
                col(UserOutput.business_date) == payload.business_date,
                col(UserOutput.story_id).is_(None),
                col(UserOutput.monitor_id).is_(None),
                col(UserOutput.request_id).is_(None),
            ),
        ).one_or_none()

    def _ensure_user_output_exists(self, *, session: Session, output_id: str) -> None:
        row = session.exec(
            select(col(UserOutput.output_id)).where(
                col(UserOutput.user_id) == self.user_id,
                col(UserOutput.output_id) == output_id,
            ),
        ).one_or_none()
        if row is None:
            raise ValueError(f"Unknown output_id for user scope: {output_id}")

    def _ensure_block_matches_output(
        self,
        *,
        session: Session,
        output_id: str,
        output_block_id: int,
    ) -> None:
        block = session.exec(
            select(UserOutputBlock).where(
                col(UserOutputBlock.user_id) == self.user_id,
                col(UserOutputBlock.block_id) == output_block_id,
            ),
        ).one_or_none()
        if block is None:
            raise ValueError(f"Unknown output_block_id for user scope: {output_block_id}")
        if block.output_id != output_id:
            raise ValueError(
                "output_block_id does not belong to output_id in current user scope "
                f"(output_id={output_id}, output_block_id={output_block_id}).",
            )

    def _upsert_user_output_in_session(
        self,
        *,
        session: Session,
        payload: UserOutputUpsert,
    ) -> UserOutput:
        now = utc_now()
        row = self._resolve_existing_user_output(session=session, payload=payload)
        if row is None:
            row = UserOutput(
                output_id=str(uuid4()),
                user_id=self.user_id,
                kind=payload.kind,
                business_date=payload.business_date,
                story_id=payload.story_id,
                monitor_id=payload.monitor_id,
                request_id=payload.request_id,
                task_id=payload.task_id,
                status=payload.status,
                title=payload.title,
                payload_json=json.dumps(payload.payload, ensure_ascii=False, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
        else:
            row.business_date = payload.business_date
            row.story_id = payload.story_id
            row.monitor_id = payload.monitor_id
            row.request_id = payload.request_id
            row.task_id = payload.task_id
            row.status = payload.status
            row.title = payload.title
            row.payload_json = json.dumps(payload.payload, ensure_ascii=False, sort_keys=True)
            row.updated_at = now
            session.add(row)

        session.exec(
            delete(UserOutputBlock).where(
                col(UserOutputBlock.user_id) == self.user_id,
                col(UserOutputBlock.output_id) == row.output_id,
            ),
        )
        for block in payload.blocks:
            session.add(
                UserOutputBlock(
                    user_id=self.user_id,
                    output_id=row.output_id,
                    block_order=block.block_order,
                    text=block.text,
                    source_ids_json=json.dumps(
                        list(block.source_ids),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    created_at=now,
                ),
            )
        return row

    def _get_task_row_for_update(self, *, session: Session, task_id: str) -> LlmTask:
        row = session.exec(
            select(LlmTask).where(
                LlmTask.task_id == task_id,
                LlmTask.user_id == self.user_id,
            ),
        ).one_or_none()
        if row is None:
            raise RuntimeError(f"Task not found: {task_id}")
        return row

    def _add_event(  # noqa: PLR0913
        self,
        *,
        session: Session,
        task_id: str,
        event_type: str,
        status_from: LlmTaskStatus | None,
        status_to: LlmTaskStatus | None,
        details: dict[str, object],
    ) -> None:
        session.add(
            LlmTaskEvent(
                task_id=task_id,
                user_id=self.user_id,
                event_type=event_type,
                status_from=status_from.value if status_from is not None else None,
                status_to=status_to.value if status_to is not None else None,
                details_json=json.dumps(details, ensure_ascii=False, sort_keys=True)
                if details
                else None,
                created_at=utc_now(),
            ),
        )


def _to_db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _to_utc_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_task_view(row: LlmTask) -> LlmTaskView:
    return LlmTaskView(
        task_id=row.task_id,
        user_id=row.user_id,
        task_type=row.task_type,
        priority=row.priority,
        status=LlmTaskStatus(row.status),
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        timeout_seconds=row.timeout_seconds,
        run_after=_to_utc_aware_datetime(row.run_after),
        started_at=_to_utc_aware_datetime(row.started_at) if row.started_at is not None else None,
        heartbeat_at=(
            _to_utc_aware_datetime(row.heartbeat_at) if row.heartbeat_at is not None else None
        ),
        finished_at=(
            _to_utc_aware_datetime(row.finished_at) if row.finished_at is not None else None
        ),
        failure_class=FailureClass(row.failure_class) if row.failure_class is not None else None,
        last_exit_code=row.last_exit_code,
        repair_attempted_at=(
            _to_utc_aware_datetime(row.repair_attempted_at)
            if row.repair_attempted_at is not None
            else None
        ),
        worker_id=row.worker_id,
        input_manifest_path=row.input_manifest_path,
        output_path=row.output_path,
        error_summary=row.error_summary,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_task_event_view(row: LlmTaskEvent) -> LlmTaskEventView:
    details: dict[str, object] = {}
    if row.details_json:
        parsed = json.loads(row.details_json)
        if isinstance(parsed, dict):
            details = parsed
    return LlmTaskEventView(
        event_id=row.id or 0,
        task_id=row.task_id,
        event_type=row.event_type,
        status_from=LlmTaskStatus(row.status_from) if row.status_from is not None else None,
        status_to=LlmTaskStatus(row.status_to) if row.status_to is not None else None,
        created_at=_to_utc_aware_datetime(row.created_at),
        details=details,
    )


def _to_task_attempt_view(row: LlmTaskAttempt) -> LlmTaskAttemptView:
    failure_class: FailureClass | None = None
    if row.failure_class is not None:
        try:
            failure_class = FailureClass(row.failure_class)
        except ValueError:
            failure_class = None
    return LlmTaskAttemptView(
        attempt_id=row.attempt_id or 0,
        task_id=row.task_id,
        user_id=row.user_id,
        attempt_no=row.attempt_no,
        task_type=row.task_type,
        status=row.status,
        started_at=_to_utc_aware_datetime(row.started_at),
        finished_at=(
            _to_utc_aware_datetime(row.finished_at) if row.finished_at is not None else None
        ),
        duration_ms=row.duration_ms,
        worker_id=row.worker_id,
        agent=row.agent,
        model=row.model,
        profile=row.profile,
        command_template_hash=row.command_template_hash,
        exit_code=row.exit_code,
        timed_out=row.timed_out,
        failure_class=failure_class,
        attempt_failure_code=row.attempt_failure_code,
        error_summary_sanitized=row.error_summary_sanitized,
        stdout_preview_sanitized=row.stdout_preview_sanitized,
        stderr_preview_sanitized=row.stderr_preview_sanitized,
        output_chars=row.output_chars,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        usage_status=row.usage_status,
        usage_source=row.usage_source,
        usage_parser_version=row.usage_parser_version,
        estimated_cost_usd=row.estimated_cost_usd,
        created_at=_to_utc_aware_datetime(row.created_at),
    )


def _to_story_definition_view(row: UserStoryDefinition) -> StoryDefinitionView:
    return StoryDefinitionView(
        story_id=row.story_id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        target_language=row.target_language,
        priority=row.priority,
        enabled=row.enabled,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_monitor_question_view(row: MonitorQuestion) -> MonitorQuestionView:
    return MonitorQuestionView(
        monitor_id=row.monitor_id,
        user_id=row.user_id,
        name=row.name,
        prompt=row.prompt,
        cadence=row.cadence,
        enabled=row.enabled,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_daily_story_snapshot_view(row: DailyStorySnapshot) -> DailyStorySnapshotView:
    summary: dict[str, object] = {}
    try:
        parsed = json.loads(row.summary_json)
        if isinstance(parsed, dict):
            summary = parsed
    except json.JSONDecodeError:
        summary = {}
    return DailyStorySnapshotView(
        business_date=row.business_date,
        story_id=row.story_id,
        story_key=row.story_key,
        title=row.title,
        continuity_key=row.continuity_key,
        summary=summary,
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_user_output_view(
    row: UserOutput,
    block_rows: Sequence[UserOutputBlock],
) -> UserOutputView:
    payload: dict[str, object] = {}
    try:
        parsed_payload = json.loads(row.payload_json)
        if isinstance(parsed_payload, dict):
            payload = parsed_payload
    except json.JSONDecodeError:
        payload = {}
    blocks: list[UserOutputBlockWrite] = []
    for block_row in block_rows:
        try:
            parsed_source_ids = json.loads(block_row.source_ids_json)
        except json.JSONDecodeError:
            parsed_source_ids = []
        source_ids = tuple(
            value for value in parsed_source_ids if isinstance(value, str) and value.strip()
        )
        blocks.append(
            UserOutputBlockWrite(
                block_order=block_row.block_order,
                text=block_row.text,
                source_ids=source_ids,
            ),
        )
    return UserOutputView(
        output_id=row.output_id,
        user_id=row.user_id,
        kind=row.kind,
        business_date=row.business_date,
        status=row.status,
        story_id=row.story_id,
        monitor_id=row.monitor_id,
        request_id=row.request_id,
        task_id=row.task_id,
        title=row.title,
        payload=payload,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
        blocks=blocks,
    )


def _article_id_from_source_id(source_id: str) -> str | None:
    prefix = "article:"
    if not source_id.startswith(prefix):
        return None
    article_id = source_id[len(prefix) :].strip()
    if not article_id:
        return None
    return article_id
