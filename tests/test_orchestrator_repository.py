from __future__ import annotations

import multiprocessing
import os
import queue
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import allure
import pytest

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import NormalizedArticle
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.orchestrator.models import (
    FailureClass,
    LlmTaskAttemptFinish,
    LlmTaskCreate,
    LlmTaskStatus,
    OutputFeedbackWrite,
    OutputCitationSnapshotWrite,
    ReadStateEventWrite,
    UserOutputBlockWrite,
    UserOutputUpsert,
)
from news_recap.orchestrator.repository import OrchestratorRepository

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Task Queue Reliability"),
]


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


def _run_terminal_mutation_thread(  # pragma: no cover - timing-sensitive helper
    db_path: str,
    task_id: str,
    action: str,
    start_event: threading.Event,
    result_queue: queue.Queue[tuple[str, str, str]],
) -> None:
    repository = OrchestratorRepository(Path(db_path))
    try:
        start_event.wait(timeout=2)
        if action == "complete":
            completed = repository.complete_task(
                task_id=task_id,
                output_path="stress-output.json",
                citations=[
                    OutputCitationSnapshotWrite(
                        source_id="article:stress",
                        article_id=None,
                        title="Stress citation",
                        url="https://example.com/stress",
                        source="example.com",
                        published_at=None,
                    ),
                ],
            )
            result_queue.put((action, "ok" if completed else "noop", ""))
            return
        if action == "cancel":
            repository.cancel_task(task_id=task_id)
            result_queue.put((action, "ok", ""))
            return
        if action == "retry":
            repository.retry_task(task_id=task_id)
            result_queue.put((action, "ok", ""))
            return
        raise RuntimeError(f"Unsupported action: {action}")
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


def test_recover_stale_running_tasks_requeues_with_event(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "orchestrator-stale-running.db")
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            timeout_seconds=60,
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None
    assert claimed.status == LlmTaskStatus.RUNNING

    stale_started_at = (datetime.now(tz=UTC) - timedelta(hours=2)).replace(tzinfo=None)
    repository._connection.execute(
        "UPDATE llm_tasks SET started_at = ?, heartbeat_at = ? WHERE task_id = ?",
        (
            stale_started_at.isoformat(sep=" "),
            stale_started_at.isoformat(sep=" "),
            task.task_id,
        ),
    )
    repository._connection.commit()

    recovered = repository.recover_stale_running_tasks(stale_after=timedelta(seconds=30))
    assert recovered == 1

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.QUEUED
    assert any(event.event_type == "stale_recovered" for event in details.events)
    repository.close()


def test_finalize_task_attempt_fallback_preserves_non_zero_duration(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "orchestrator-attempt-fallback.db")
    repository.init_schema()

    task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            timeout_seconds=120,
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    claimed = repository.claim_next_ready_task(worker_id="worker-a")
    assert claimed is not None

    started_at = claimed.started_at
    assert started_at is not None
    finished_at = started_at + timedelta(seconds=2)

    repository.finalize_task_attempt(
        LlmTaskAttemptFinish(
            task_id=task.task_id,
            attempt_no=claimed.attempt,
            started_at=started_at,
            status="failed",
            finished_at=finished_at,
            exit_code=2,
            timed_out=False,
            failure_class=FailureClass.BACKEND_NON_RETRYABLE,
            attempt_failure_code="fallback_row_created",
            error_summary_sanitized="fallback finalize",
            stdout_preview_sanitized="",
            stderr_preview_sanitized="",
            output_chars=None,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            usage_status="unknown",
            usage_source="none",
            usage_parser_version="v1",
            estimated_cost_usd=None,
        ),
    )

    attempts = repository.list_task_attempts(task_id=task.task_id)
    assert len(attempts) == 1
    assert attempts[0].duration_ms is not None
    assert attempts[0].duration_ms >= 2000
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


def test_validate_user_source_ids_is_user_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "source-scope.db"

    repo_a_ingest = SQLiteRepository(db_path, user_id="user_a", user_name="User A")
    repo_a_ingest.init_schema()
    run_id = repo_a_ingest.start_run(source="rss")
    canonical = canonicalize_url("https://example.com/news/1")
    result = repo_a_ingest.upsert_article(
        article=NormalizedArticle(
            source_name="rss",
            external_id="shared-1",
            url="https://example.com/news/1",
            url_canonical=canonical,
            url_hash=url_hash(canonical),
            title="Shared article",
            source_domain=extract_domain(canonical),
            published_at=datetime(2026, 2, 18, 12, 0, tzinfo=UTC),
            language_detected="en",
            content_raw="seed",
            summary_raw=None,
            is_full_content=True,
            needs_enrichment=False,
            clean_text="seed",
            clean_text_chars=4,
            is_truncated=False,
        ),
        run_id=run_id,
    )
    repo_a_ingest.close()

    source_id = f"article:{result.article_id}"
    repo_a = OrchestratorRepository(db_path, user_id="user_a", user_name="User A")
    repo_a.init_schema()
    resolved_a, missing_a = repo_a.validate_user_source_ids(source_ids=(source_id,))
    assert missing_a == []
    assert len(resolved_a) == 1
    assert resolved_a[0].source_id == source_id
    repo_a.close()

    repo_b = OrchestratorRepository(db_path, user_id="user_b", user_name="User B")
    repo_b.init_schema()
    resolved_b, missing_b = repo_b.validate_user_source_ids(source_ids=(source_id,))
    assert resolved_b == []
    assert missing_b == [source_id]
    repo_b.close()


def test_output_citation_snapshots_survive_global_article_gc(tmp_path: Path) -> None:
    db_path = tmp_path / "citation-snapshots.db"

    ingest = SQLiteRepository(db_path)
    ingest.init_schema()
    run_id = ingest.start_run(source="rss")
    canonical = canonicalize_url("https://example.com/news/citation")
    upsert = ingest.upsert_article(
        article=NormalizedArticle(
            source_name="rss",
            external_id="citation-seed",
            url="https://example.com/news/citation",
            url_canonical=canonical,
            url_hash=url_hash(canonical),
            title="Citation article",
            source_domain=extract_domain(canonical),
            published_at=datetime(2026, 2, 18, 12, 0, tzinfo=UTC),
            language_detected="en",
            content_raw="seed",
            summary_raw=None,
            is_full_content=True,
            needs_enrichment=False,
            clean_text="seed",
            clean_text_chars=4,
            is_truncated=False,
        ),
        run_id=run_id,
    )
    article_id = upsert.article_id

    orchestrator = OrchestratorRepository(db_path)
    orchestrator.init_schema()
    task = orchestrator.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest.json"),
        ),
    )
    inserted = orchestrator.persist_output_citation_snapshots(
        task_id=task.task_id,
        citations=[
            OutputCitationSnapshotWrite(
                source_id=f"article:{article_id}",
                article_id=article_id,
                title="Citation article",
                url="https://example.com/news/citation",
                source="example.com",
                published_at=datetime(2026, 2, 18, 12, 0, tzinfo=UTC),
            ),
        ],
    )
    assert inserted == 1
    orchestrator.close()

    # Remove user link first (per-user prune), then run global GC.
    old_discovered_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    ingest._connection.execute(
        "UPDATE user_articles SET discovered_at = ? WHERE user_id = ? AND article_id = ?",
        (old_discovered_at.isoformat(), ingest.user_id, article_id),
    )
    ingest._connection.commit()

    ingest.prune_articles(cutoff=datetime.now(tz=UTC))
    gc_result = ingest.gc_unreferenced_articles()
    assert gc_result.articles_deleted == 1

    verify = OrchestratorRepository(db_path)
    verify.init_schema()
    citations = verify.list_output_citations(task_id=task.task_id)
    assert len(citations) == 1
    assert citations[0].source_id == f"article:{article_id}"
    assert citations[0].title == "Citation article"
    assert citations[0].url == "https://example.com/news/citation"
    verify.close()
    ingest.close()


def test_read_state_and_feedback_reject_mismatched_output_block_scope(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "output-scope.db")
    repository.init_schema()

    output_a = repository.upsert_user_output(
        UserOutputUpsert(
            kind="highlights",
            business_date=date(2026, 2, 18),
            status="ready",
            payload={"kind": "a"},
            blocks=[
                UserOutputBlockWrite(
                    block_order=0,
                    text="A",
                    source_ids=("article:a",),
                ),
            ],
        ),
    )
    output_b = repository.upsert_user_output(
        UserOutputUpsert(
            kind="qa_answer",
            business_date=date(2026, 2, 18),
            status="ready",
            request_id="request-b",
            payload={"kind": "b"},
            blocks=[
                UserOutputBlockWrite(
                    block_order=0,
                    text="B",
                    source_ids=("article:b",),
                ),
            ],
        ),
    )

    row_b = repository._connection.execute(
        "SELECT block_id FROM user_output_blocks WHERE user_id = ? AND output_id = ? LIMIT 1",
        (repository.user_id, output_b.output_id),
    ).fetchone()
    assert row_b is not None
    block_b_id = int(row_b["block_id"])

    with pytest.raises(ValueError, match="does not belong to output_id"):
        repository.add_read_state_event(
            ReadStateEventWrite(
                output_id=output_a.output_id,
                output_block_id=block_b_id,
                event_type="open",
            ),
        )

    with pytest.raises(ValueError, match="does not belong to output_id"):
        repository.add_output_feedback(
            OutputFeedbackWrite(
                output_id=output_a.output_id,
                output_block_id=block_b_id,
                feedback_type="hide",
            ),
        )
    repository.close()


def test_list_recent_read_source_ids_respects_block_scope(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "read-state-scope.db")
    repository.init_schema()

    output = repository.upsert_user_output(
        UserOutputUpsert(
            kind="highlights",
            business_date=date(2026, 2, 18),
            status="ready",
            payload={"summary": "test"},
            blocks=[
                UserOutputBlockWrite(
                    block_order=0,
                    text="Block 1",
                    source_ids=("article:1",),
                ),
                UserOutputBlockWrite(
                    block_order=1,
                    text="Block 2",
                    source_ids=("article:2",),
                ),
            ],
        ),
    )

    rows = repository._connection.execute(
        "SELECT block_id, block_order FROM user_output_blocks WHERE user_id = ? AND output_id = ? ORDER BY block_order",
        (repository.user_id, output.output_id),
    ).fetchall()
    assert len(rows) == 2
    first_block_id = int(rows[0]["block_id"])

    repository.add_read_state_event(
        ReadStateEventWrite(
            output_id=output.output_id,
            output_block_id=first_block_id,
            event_type="open",
        ),
    )
    repository.add_read_state_event(
        ReadStateEventWrite(
            output_id=output.output_id,
            output_block_id=None,
            event_type="open",
        ),
    )

    seen = repository.list_recent_read_source_ids(days=3)
    assert seen == {"article:1"}
    repository.close()


def test_list_tasks_for_metrics_uses_activity_window_and_status_filter(
    tmp_path: Path,
) -> None:
    repository = OrchestratorRepository(tmp_path / "orchestrator-metrics-window.db")
    repository.init_schema()

    recent_task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest-recent.json"),
        ),
    )
    claimed_recent = repository.claim_next_ready_task(worker_id="worker-recent")
    assert claimed_recent is not None
    assert (
        repository.fail_task(
            task_id=recent_task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=FailureClass.BACKEND_NON_RETRYABLE,
            error_summary="recent terminal",
            last_exit_code=2,
        )
        is True
    )

    old_task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="highlights",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest-old.json"),
        ),
    )
    claimed_old = repository.claim_next_ready_task(worker_id="worker-old")
    assert claimed_old is not None
    assert (
        repository.fail_task(
            task_id=old_task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=FailureClass.BACKEND_NON_RETRYABLE,
            error_summary="old terminal",
            last_exit_code=2,
        )
        is True
    )

    queued_task = repository.enqueue_task(
        LlmTaskCreate(
            task_type="qa",
            run_after=datetime.now(tz=UTC),
            input_manifest_path=str(tmp_path / "manifest-queued.json"),
        ),
    )

    now = datetime.now(tz=UTC)
    old_timestamp = now - timedelta(days=7)
    repository._connection.execute(
        "UPDATE llm_tasks SET created_at = ?, finished_at = ?, updated_at = ? WHERE task_id = ?",
        (
            old_timestamp.replace(tzinfo=None).isoformat(sep=" "),
            now.replace(tzinfo=None).isoformat(sep=" "),
            now.replace(tzinfo=None).isoformat(sep=" "),
            recent_task.task_id,
        ),
    )
    repository._connection.execute(
        "UPDATE llm_tasks SET created_at = ?, finished_at = ?, updated_at = ? WHERE task_id = ?",
        (
            old_timestamp.replace(tzinfo=None).isoformat(sep=" "),
            old_timestamp.replace(tzinfo=None).isoformat(sep=" "),
            old_timestamp.replace(tzinfo=None).isoformat(sep=" "),
            old_task.task_id,
        ),
    )
    repository._connection.commit()

    cutoff = now - timedelta(hours=1)
    window_tasks = repository.list_tasks_for_metrics(since=cutoff)
    window_task_ids = {task.task_id for task in window_tasks}
    assert recent_task.task_id in window_task_ids
    assert old_task.task_id not in window_task_ids

    active_tasks = repository.list_tasks_for_metrics(
        statuses=(LlmTaskStatus.QUEUED, LlmTaskStatus.RUNNING),
    )
    assert {task.task_id for task in active_tasks} == {queued_task.task_id}
    repository.close()


@pytest.mark.skipif(
    os.getenv("NEWS_RECAP_RUN_STRESS_TESTS") != "1",
    reason="Set NEWS_RECAP_RUN_STRESS_TESTS=1 to run long concurrency stress tests.",
)
def test_stress_concurrent_cancel_retry_complete(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator-stress-races.db"
    iterations = int(os.getenv("NEWS_RECAP_STRESS_ITERATIONS", "200"))
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    for index in range(iterations):
        task = repository.enqueue_task(
            LlmTaskCreate(
                task_type="highlights",
                run_after=datetime.now(tz=UTC),
                input_manifest_path=str(tmp_path / f"manifest-{index}.json"),
            ),
        )
        claimed = repository.claim_next_ready_task(worker_id=f"stress-worker-{index}")
        assert claimed is not None
        assert claimed.task_id == task.task_id
        assert claimed.status == LlmTaskStatus.RUNNING

        start_event = threading.Event()
        result_queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        threads = [
            threading.Thread(
                target=_run_terminal_mutation_thread,
                args=(str(db_path), task.task_id, action, start_event, result_queue),
                daemon=True,
            )
            for action in ("complete", "cancel", "retry")
        ]
        for thread in threads:
            thread.start()
        start_event.set()
        for thread in threads:
            thread.join(timeout=5)
            assert thread.is_alive() is False

        _results = [result_queue.get(), result_queue.get(), result_queue.get()]
        details = repository.get_task_details(task_id=task.task_id)
        assert details is not None

        status = details.task.status
        assert status in {LlmTaskStatus.SUCCEEDED, LlmTaskStatus.CANCELED, LlmTaskStatus.QUEUED}

        event_types = [event.event_type for event in details.events]
        assert event_types.count("succeeded") <= 1
        assert event_types.count("canceled") <= 1
        assert event_types.count("manual_retry") <= 1
        assert not (event_types.count("succeeded") == 1 and event_types.count("canceled") == 1)

        citations = repository.list_output_citations(task_id=task.task_id)
        if status == LlmTaskStatus.SUCCEEDED:
            assert len(citations) == 1
            assert citations[0].source_id == "article:stress"
        else:
            assert citations == []

    repository.close()
