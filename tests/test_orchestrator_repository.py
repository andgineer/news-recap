from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime
from pathlib import Path

from news_recap.orchestrator.models import FailureClass, LlmTaskCreate, LlmTaskStatus
from news_recap.orchestrator.repository import OrchestratorRepository


def _run_manual_mutation(  # pragma: no cover - executed in child process
    db_path: str,
    task_id: str,
    action: str,
    start_event: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue[tuple[str, str, str]],
) -> None:
    repository = OrchestratorRepository(Path(db_path))
    try:
        start_event.wait(timeout=5)
        if action == "retry":
            repository.retry_task(task_id=task_id)
        elif action == "cancel":
            repository.cancel_task(task_id=task_id)
        else:
            raise RuntimeError(f"Unsupported action: {action}")
        result_queue.put((action, "ok", ""))
    except Exception as error:  # noqa: BLE001
        result_queue.put((action, "error", str(error)))
    finally:
        repository.close()


def test_orchestrator_repository_claim_retry_and_events(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "orchestrator.db")
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            priority=5,
            max_attempts=3,
            timeout_seconds=120,
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    assert task.status == LlmTaskStatus.QUEUED
    assert task.attempt == 0

    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None
    assert claimed.task_id == task.task_id
    assert claimed.status == LlmTaskStatus.RUNNING
    assert claimed.attempt == 1

    scheduled = repository.schedule_retry(
        task_id=task.task_id,
        run_after=datetime.now(tz=UTC),
        timeout_seconds=180,
        failure_class=FailureClass.TIMEOUT,
        error_summary="Timed out.",
        last_exit_code=124,
    )
    assert scheduled is True
    queued_again = repository.list_tasks(status=LlmTaskStatus.QUEUED, limit=10)
    assert len(queued_again) == 1
    assert queued_again[0].task_id == task.task_id
    assert queued_again[0].timeout_seconds == 180

    claimed_again = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed_again is not None
    assert claimed_again.attempt == 2

    failed = repository.fail_task(
        task_id=task.task_id,
        status=LlmTaskStatus.FAILED,
        failure_class=FailureClass.BACKEND_NON_RETRYABLE,
        error_summary="Bad command.",
        last_exit_code=2,
    )
    assert failed is True
    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.FAILED
    assert details.task.failure_class == FailureClass.BACKEND_NON_RETRYABLE
    assert len(details.events) >= 4
    repository.close()


def test_cancel_is_terminal_for_running_task_updates(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "orchestrator-cancel.db")
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None
    assert claimed.task_id == task.task_id
    repository.cancel_task(task_id=task.task_id)

    assert repository.complete_task(task_id=task.task_id, output_path="out.json") is False
    assert (
        repository.fail_task(
            task_id=task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=FailureClass.BACKEND_NON_RETRYABLE,
            error_summary="should not apply",
            last_exit_code=2,
        )
        is False
    )
    assert (
        repository.schedule_retry(
            task_id=task.task_id,
            run_after=datetime.now(tz=UTC),
            timeout_seconds=120,
            failure_class=FailureClass.TIMEOUT,
            error_summary="should not apply",
            last_exit_code=124,
        )
        is False
    )

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.CANCELED
    event_types = [event.event_type for event in details.events]
    assert "canceled" in event_types
    assert "succeeded" not in event_types
    repository.close()


def test_schedule_retry_resets_repair_marker_for_next_attempt(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "orchestrator-repair-reset.db")
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None
    assert repository.mark_repair_attempted(task_id=task.task_id) is True

    scheduled = repository.schedule_retry(
        task_id=task.task_id,
        run_after=datetime.now(tz=UTC),
        timeout_seconds=200,
        failure_class=FailureClass.TIMEOUT,
        error_summary="retry",
        last_exit_code=124,
    )
    assert scheduled is True

    details_after_retry = repository.get_task_details(task_id=task.task_id)
    assert details_after_retry is not None
    assert details_after_retry.task.status == LlmTaskStatus.QUEUED
    assert details_after_retry.task.repair_attempted_at is None

    claimed_again = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed_again is not None
    assert claimed_again.attempt == 2
    assert claimed_again.repair_attempted_at is None
    repository.close()


def test_manual_retry_cancel_race_is_safe_across_processes(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator-manual-race.db"
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None
    failed = repository.fail_task(
        task_id=task.task_id,
        status=LlmTaskStatus.FAILED,
        failure_class=FailureClass.BACKEND_NON_RETRYABLE,
        error_summary="seed failed state",
        last_exit_code=2,
    )
    assert failed is True
    repository.close()

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue: multiprocessing.queues.Queue[tuple[str, str, str]] = context.Queue()
    retry_process = context.Process(
        target=_run_manual_mutation,
        args=(str(db_path), task.task_id, "retry", start_event, result_queue),
    )
    cancel_process = context.Process(
        target=_run_manual_mutation,
        args=(str(db_path), task.task_id, "cancel", start_event, result_queue),
    )

    retry_process.start()
    cancel_process.start()
    start_event.set()
    retry_process.join(timeout=10)
    cancel_process.join(timeout=10)
    assert retry_process.exitcode == 0
    assert cancel_process.exitcode == 0

    results = {
        action: (status, message)
        for action, status, message in (result_queue.get(), result_queue.get())
    }
    assert results["retry"][0] == "ok"
    assert results["cancel"][0] in {"ok", "error"}
    if results["cancel"][0] == "error":
        assert (
            "Task cannot be canceled from status=failed" in results["cancel"][1]
            or "Task state changed concurrently while canceling" in results["cancel"][1]
        )

    verify_repository = OrchestratorRepository(db_path)
    verify_repository.init_schema()
    details = verify_repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status in {LlmTaskStatus.QUEUED, LlmTaskStatus.CANCELED}
    event_types = [event.event_type for event in details.events]
    assert event_types.count("manual_retry") <= 1
    assert event_types.count("canceled") <= 1
    verify_repository.close()


def test_manual_retry_retry_race_is_safe_across_processes(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator-manual-retry-race.db"
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None
    failed = repository.fail_task(
        task_id=task.task_id,
        status=LlmTaskStatus.FAILED,
        failure_class=FailureClass.BACKEND_NON_RETRYABLE,
        error_summary="seed failed state",
        last_exit_code=2,
    )
    assert failed is True
    repository.close()

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue: multiprocessing.queues.Queue[tuple[str, str, str]] = context.Queue()
    retry_process_a = context.Process(
        target=_run_manual_mutation,
        args=(str(db_path), task.task_id, "retry", start_event, result_queue),
    )
    retry_process_b = context.Process(
        target=_run_manual_mutation,
        args=(str(db_path), task.task_id, "retry", start_event, result_queue),
    )

    retry_process_a.start()
    retry_process_b.start()
    start_event.set()
    retry_process_a.join(timeout=10)
    retry_process_b.join(timeout=10)
    assert retry_process_a.exitcode == 0
    assert retry_process_b.exitcode == 0

    results = [result_queue.get(), result_queue.get()]
    ok_count = sum(1 for _, status, _ in results if status == "ok")
    error_messages = [message for _, status, message in results if status == "error"]
    assert ok_count == 1
    assert len(error_messages) == 1
    assert (
        "Only failed/timeout/canceled tasks can be retried manually, got queued."
        in error_messages[0]
        or "Task state changed concurrently while retrying" in error_messages[0]
    )

    verify_repository = OrchestratorRepository(db_path)
    verify_repository.init_schema()
    details = verify_repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.QUEUED
    event_types = [event.event_type for event in details.events]
    assert event_types.count("manual_retry") == 1
    verify_repository.close()
