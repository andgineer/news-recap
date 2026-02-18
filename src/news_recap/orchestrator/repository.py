"""Persistent queue repository for orchestrator tasks."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy import update as sa_update
from sqlmodel import Session, col, create_engine, select

from news_recap.ingestion.storage.alembic_runner import upgrade_head
from news_recap.ingestion.storage.common import utc_now
from news_recap.ingestion.storage.sqlmodel_models import (
    DEFAULT_USER_ID,
    AppUser,
    LlmTask,
    LlmTaskArtifact,
    LlmTaskEvent,
)
from news_recap.orchestrator.models import (
    FailureClass,
    LlmTaskArtifactWrite,
    LlmTaskCreate,
    LlmTaskDetails,
    LlmTaskEventView,
    LlmTaskStatus,
    LlmTaskView,
)


class OrchestratorRepository:
    """Queue persistence facade backed by SQLModel + SQLite."""

    def __init__(
        self,
        db_path: Path,
        *,
        user_id: str = DEFAULT_USER_ID,
        user_name: str = "Default User",
    ) -> None:
        self.db_path = db_path
        self.user_id = user_id
        self.user_name = user_name

        db_url = f"sqlite:///{db_path}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)

        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        """Close underlying DB resources."""

        self._connection.close()
        self.engine.dispose()

    def init_schema(self) -> None:
        """Run schema migrations and ensure actor context exists."""

        upgrade_head(self.db_path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.commit()
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
            self._add_event(
                session=session,
                task_id=task_id,
                event_type="succeeded",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.SUCCEEDED,
                details={"output_path": output_path},
            )
            session.commit()
            return True

    def fail_task(
        self,
        *,
        task_id: str,
        status: LlmTaskStatus,
        failure_class: FailureClass,
        error_summary: str,
        last_exit_code: int | None,
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
                },
            )
            session.commit()
            return True

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

        events: list[LlmTaskEventView] = []
        for row in event_rows:
            details = {}
            if row.details_json:
                parsed = json.loads(row.details_json)
                if isinstance(parsed, dict):
                    details = parsed
            events.append(
                LlmTaskEventView(
                    event_id=row.id or 0,
                    task_id=row.task_id,
                    event_type=row.event_type,
                    status_from=(
                        LlmTaskStatus(row.status_from) if row.status_from is not None else None
                    ),
                    status_to=LlmTaskStatus(row.status_to) if row.status_to is not None else None,
                    created_at=_to_utc_aware_datetime(row.created_at),
                    details=details,
                ),
            )

        return LlmTaskDetails(task=_to_task_view(task), events=events)

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


def _enable_sqlite_foreign_keys(dbapi_connection: sqlite3.Connection, _: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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
