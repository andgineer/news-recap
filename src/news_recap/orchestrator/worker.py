"""Queue worker that executes CLI-backed LLM tasks."""

from __future__ import annotations

import hashlib
import json
import random
import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from news_recap.ingestion.storage.common import utc_now
from news_recap.orchestrator.backend import (
    BackendRunError,
    BackendRunRequest,
    BackendRunResult,
    CliAgentBackend,
)
from news_recap.orchestrator.contracts import (
    ArticleIndexEntry,
    TaskInputContract,
    TaskManifest,
    read_articles_index,
    read_manifest,
    read_task_input,
    write_agent_output,
)
from news_recap.orchestrator.failure_classifier import classify_backend_failure
from news_recap.orchestrator.models import (
    FailureClass,
    LlmTaskAttemptFinish,
    LlmTaskAttemptStart,
    LlmTaskStatus,
    LlmTaskView,
    OutputCitationSnapshotWrite,
    UserOutputBlockWrite,
    UserOutputUpsert,
)
from news_recap.orchestrator.output_fallback import (
    STDOUT_PARSER_VERSION,
    recover_output_contract_from_stdout,
)
from news_recap.orchestrator.pricing import estimate_cost_usd
from news_recap.orchestrator.repair import decide_repair
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import (
    FrozenRouting,
    RoutingDefaults,
    resolve_routing_for_execution,
)
from news_recap.orchestrator.sanitization import sanitize_preview
from news_recap.orchestrator.usage import extract_usage
from news_recap.orchestrator.validator import validate_output_contract


@dataclass(slots=True)
class WorkerRunSummary:
    """Aggregate worker counters for CLI reporting."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    timeouts: int = 0
    idle_polls: int = 0


class RetryOutcome(NamedTuple):
    retried: bool
    failed: bool


@dataclass(slots=True)
class LoadInputsResult:
    """Loaded manifest/input/index with upfront validation result."""

    ok: bool
    manifest_path: Path | None
    manifest: TaskManifest | None
    task_input: TaskInputContract | None
    article_entries: list[ArticleIndexEntry]
    allowed_source_ids: set[str]
    error_summary: str | None
    failure_class: FailureClass | None
    attempt_failure_code: str | None
    output_path: Path | None


@dataclass(slots=True)
class ExecutionAttemptResult:
    """Execution phase result after routing and backend invocation."""

    ok: bool
    routing: FrozenRouting | None
    execution: BackendRunResult | None
    failure_class: FailureClass | None
    attempt_failure_code: str | None
    error_summary: str | None
    details: dict[str, object] | None


class OrchestratorWorker:
    """Consumes queued tasks and executes them via backend."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        repository: OrchestratorRepository,
        backend: CliAgentBackend,
        routing_defaults: RoutingDefaults,
        worker_id: str,
        poll_interval_seconds: float = 2.0,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 900,
        timeout_retry_cap_seconds: int = 1800,
        transient_exit_codes: tuple[int, ...] = (137, 143),
        stale_attempt_seconds: int = 1800,
        graceful_shutdown_seconds: int = 30,
        backend_capability_mode: str = "manifest_native",
    ) -> None:
        self.repository = repository
        self.backend = backend
        self.routing_defaults = routing_defaults
        self.worker_id = worker_id
        self.poll_interval_seconds = poll_interval_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.timeout_retry_cap_seconds = timeout_retry_cap_seconds
        self.transient_exit_codes = transient_exit_codes
        self.stale_attempt_seconds = stale_attempt_seconds
        self.graceful_shutdown_seconds = graceful_shutdown_seconds
        self.backend_capability_mode = backend_capability_mode
        self._random = random.Random()  # noqa: S311
        self._stop_requested = False
        self._stop_signal_name: str | None = None
        self._current_task_id: str | None = None
        self._shutdown_task_id: str | None = None
        self._shutdown_completed_emitted = False

    def run_once(self) -> WorkerRunSummary:
        """Process at most one task from the queue."""

        summary = WorkerRunSummary()
        if self._stop_requested:
            summary.idle_polls = 1
            return summary

        task = self._claim_task()
        if task is None:
            summary.idle_polls = 1
            return summary

        summary.processed = 1
        self._current_task_id = task.task_id
        self._shutdown_completed_emitted = False
        attempt_started_at = task.started_at or utc_now()
        self.repository.upsert_task_attempt_start(
            LlmTaskAttemptStart(
                task_id=task.task_id,
                attempt_no=task.attempt,
                task_type=task.task_type,
                status=LlmTaskStatus.RUNNING.value,
                started_at=attempt_started_at,
                worker_id=self.worker_id,
                agent="unknown",
                model="unknown",
                profile="unknown",
                command_template_hash=None,
            ),
        )

        try:
            loaded = self._load_and_validate_inputs(task=task)
            if not loaded.ok:
                if self._handle_input_error(task=task, loaded=loaded):
                    summary.failed = 1
                return summary

            execution_result = self._execute_attempt(
                task=task,
                loaded=loaded,
                attempt_started_at=attempt_started_at,
            )
            if not execution_result.ok:
                self._handle_execution_error(
                    task=task,
                    loaded=loaded,
                    execution_result=execution_result,
                    summary=summary,
                )
                return summary

            self._process_attempt_result(
                task=task,
                loaded=loaded,
                execution_result=execution_result,
                summary=summary,
            )
            return summary
        finally:
            self._current_task_id = None
            self._emit_shutdown_completed_if_ready()

    def run_loop(
        self,
        *,
        max_tasks: int | None = None,
        max_idle_polls: int = 1,
    ) -> WorkerRunSummary:
        """Run worker loop until queue is idle or max_tasks reached.

        Args:
            max_tasks: Stop after processing this many tasks (None = unlimited).
            max_idle_polls: How many consecutive empty polls before exiting.
                Set to a higher value when running alongside a pipeline that
                enqueues tasks asynchronously.
        """

        aggregate = WorkerRunSummary()
        consecutive_idle = 0
        with self._signal_handlers():
            while True:
                if self._stop_requested:
                    return aggregate
                if max_tasks is not None and aggregate.processed >= max_tasks:
                    return aggregate

                summary = self.run_once()
                aggregate.processed += summary.processed
                aggregate.succeeded += summary.succeeded
                aggregate.failed += summary.failed
                aggregate.retried += summary.retried
                aggregate.timeouts += summary.timeouts
                aggregate.idle_polls += summary.idle_polls

                if summary.processed == 0:
                    consecutive_idle += 1
                    if consecutive_idle >= max_idle_polls:
                        return aggregate
                    self._sleep_with_stop(self.poll_interval_seconds)
                    continue

                consecutive_idle = 0
                if self._stop_requested:
                    return aggregate
                if max_tasks is None and self.poll_interval_seconds > 0:
                    self._sleep_with_stop(self.poll_interval_seconds)

    def _claim_task(self) -> LlmTaskView | None:
        self._recover_stale_attempts()
        if self._stop_requested:
            return None
        return self.repository.claim_next_ready_task(worker_id=self.worker_id)

    def _recover_stale_attempts(self) -> None:
        if self.stale_attempt_seconds <= 0:
            return
        self.repository.recover_stale_running_tasks(
            stale_after=timedelta(seconds=self.stale_attempt_seconds),
        )

    def _load_and_validate_inputs(self, *, task: LlmTaskView) -> LoadInputsResult:
        manifest_path = Path(task.input_manifest_path)
        try:
            manifest = read_manifest(manifest_path)
            task_input = read_task_input(Path(manifest.task_input_path))
            article_entries = read_articles_index(Path(manifest.articles_index_path))
        except Exception as error:  # noqa: BLE001
            return LoadInputsResult(
                ok=False,
                manifest_path=manifest_path,
                manifest=None,
                task_input=None,
                article_entries=[],
                allowed_source_ids=set(),
                error_summary=f"Input contract error: {error}",
                failure_class=FailureClass.INPUT_CONTRACT_ERROR,
                attempt_failure_code="input_manifest_invalid",
                output_path=None,
            )

        artifact_error = _validate_required_artifacts(
            task_type=task.task_type,
            manifest=manifest,
            task_input_metadata=task_input.metadata,
        )
        if artifact_error is not None:
            return LoadInputsResult(
                ok=False,
                manifest_path=manifest_path,
                manifest=manifest,
                task_input=task_input,
                article_entries=article_entries,
                allowed_source_ids={entry.source_id for entry in article_entries},
                error_summary=artifact_error,
                failure_class=FailureClass.INPUT_CONTRACT_ERROR,
                attempt_failure_code="input_required_artifact_missing",
                output_path=Path(manifest.output_result_path),
            )

        return LoadInputsResult(
            ok=True,
            manifest_path=manifest_path,
            manifest=manifest,
            task_input=task_input,
            article_entries=article_entries,
            allowed_source_ids={entry.source_id for entry in article_entries},
            error_summary=None,
            failure_class=None,
            attempt_failure_code=None,
            output_path=Path(manifest.output_result_path),
        )

    def _handle_input_error(self, *, task: LlmTaskView, loaded: LoadInputsResult) -> bool:
        if loaded.failure_class is None or loaded.error_summary is None:
            raise RuntimeError("Input error must include failure_class and error_summary.")
        self._finalize_attempt(
            task=task,
            status=LlmTaskStatus.FAILED,
            failure_class=loaded.failure_class,
            attempt_failure_code=loaded.attempt_failure_code,
            error_summary=loaded.error_summary,
            execution=None,
            routing=None,
            output_path=loaded.output_path,
        )
        return self.repository.fail_task(
            task_id=task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=loaded.failure_class,
            error_summary=loaded.error_summary,
            last_exit_code=None,
        )

    def _execute_attempt(
        self,
        *,
        task: LlmTaskView,
        loaded: LoadInputsResult,
        attempt_started_at: datetime,
    ) -> ExecutionAttemptResult:
        if loaded.task_input is None or loaded.manifest is None or loaded.manifest_path is None:
            raise RuntimeError("Loaded inputs are missing task_input/manifest data.")

        routing, fallback_reason = resolve_routing_for_execution(
            task_input=loaded.task_input,
            task_type=task.task_type,
            defaults=self.routing_defaults,
        )
        self.repository.upsert_task_attempt_start(
            LlmTaskAttemptStart(
                task_id=task.task_id,
                attempt_no=task.attempt,
                task_type=task.task_type,
                status=LlmTaskStatus.RUNNING.value,
                started_at=attempt_started_at,
                worker_id=self.worker_id,
                agent=routing.agent,
                model=routing.model,
                profile=routing.profile,
                command_template_hash=_command_template_hash(routing.command_template),
            ),
        )
        if fallback_reason is not None:
            self.repository.add_task_event(
                task_id=task.task_id,
                event_type="routing_fallback_applied",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.RUNNING,
                details={
                    "reason": fallback_reason,
                    "routing": routing.to_metadata(),
                },
            )

        try:
            execution = self._execute_backend(
                task_id=task.task_id,
                manifest_path=loaded.manifest_path,
                task=task,
                routing=routing,
            )
        except BackendRunError as error:
            failure_class = (
                FailureClass.BACKEND_TRANSIENT
                if error.transient
                else FailureClass.BACKEND_NON_RETRYABLE
            )
            return ExecutionAttemptResult(
                ok=False,
                routing=routing,
                execution=None,
                failure_class=failure_class,
                attempt_failure_code=f"{routing.agent}_backend_run_error",
                error_summary=str(error),
                details={
                    "reason_code": f"{routing.agent}_backend_run_error",
                    "resolved_agent": routing.agent,
                    "resolved_model": routing.model,
                    "resolved_profile": routing.profile,
                },
            )
        return ExecutionAttemptResult(
            ok=True,
            routing=routing,
            execution=execution,
            failure_class=None,
            attempt_failure_code=None,
            error_summary=None,
            details=None,
        )

    def _handle_execution_error(
        self,
        *,
        task: LlmTaskView,
        loaded: LoadInputsResult,
        execution_result: ExecutionAttemptResult,
        summary: WorkerRunSummary,
    ) -> None:
        if execution_result.failure_class is None or execution_result.error_summary is None:
            raise RuntimeError("Execution error must include failure_class and error_summary.")
        self._finalize_attempt(
            task=task,
            status=LlmTaskStatus.FAILED,
            failure_class=execution_result.failure_class,
            attempt_failure_code=execution_result.attempt_failure_code,
            error_summary=execution_result.error_summary,
            execution=execution_result.execution,
            routing=execution_result.routing,
            output_path=loaded.output_path,
        )
        if execution_result.failure_class == FailureClass.BACKEND_TRANSIENT:
            outcome = self._handle_retry_or_fail(
                task_id=task.task_id,
                task_attempt=task.attempt,
                max_attempts=task.max_attempts,
                failure_class=execution_result.failure_class,
                error_summary=execution_result.error_summary,
                last_exit_code=None,
                timeout_seconds=task.timeout_seconds,
                status_on_final=LlmTaskStatus.FAILED,
                details=execution_result.details,
            )
            if outcome.retried:
                summary.retried = 1
            elif outcome.failed:
                summary.failed = 1
            return

        failed = self.repository.fail_task(
            task_id=task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=execution_result.failure_class,
            error_summary=execution_result.error_summary,
            last_exit_code=None,
            details=execution_result.details,
        )
        if failed:
            summary.failed = 1

    def _process_attempt_result(  # noqa: C901, PLR0911, PLR0912, PLR0915
        self,
        *,
        task: LlmTaskView,
        loaded: LoadInputsResult,
        execution_result: ExecutionAttemptResult,
        summary: WorkerRunSummary,
    ) -> None:
        if loaded.manifest is None or loaded.task_input is None or loaded.output_path is None:
            raise RuntimeError("Loaded inputs are incomplete for execution processing.")
        if execution_result.execution is None or execution_result.routing is None:
            raise RuntimeError("Execution result is incomplete for processing.")

        manifest = loaded.manifest
        task_input = loaded.task_input
        execution = execution_result.execution
        routing = execution_result.routing
        allowed_source_ids = loaded.allowed_source_ids

        if execution.timed_out:
            self._finalize_attempt(
                task=task,
                status=LlmTaskStatus.TIMEOUT,
                failure_class=FailureClass.TIMEOUT,
                attempt_failure_code="process_timeout",
                error_summary="Task timed out.",
                execution=execution,
                routing=routing,
                output_path=loaded.output_path,
            )
            timeout_seconds = min(int(task.timeout_seconds * 1.5), self.timeout_retry_cap_seconds)
            outcome = self._handle_retry_or_fail(
                task_id=task.task_id,
                task_attempt=task.attempt,
                max_attempts=task.max_attempts,
                failure_class=FailureClass.TIMEOUT,
                error_summary="Task timed out.",
                last_exit_code=execution.exit_code,
                timeout_seconds=timeout_seconds,
                status_on_final=LlmTaskStatus.TIMEOUT,
            )
            if outcome.retried:
                summary.retried = 1
            elif outcome.failed:
                summary.failed = 1
                summary.timeouts = 1
            return

        if execution.exit_code != 0:
            stdout_preview = sanitize_preview(self._read_preview(execution.stdout_path))
            stderr_preview = sanitize_preview(self._read_preview(execution.stderr_path))
            classification = classify_backend_failure(
                agent=routing.agent,
                exit_code=execution.exit_code,
                stdout=stdout_preview,
                stderr=stderr_preview,
                transient_exit_codes=self.transient_exit_codes,
            )
            failure_details: dict[str, object] = classification.to_event_details(
                agent=routing.agent,
                model=routing.model,
            )
            failure_details["resolved_profile"] = routing.profile
            failure_details["stdout_preview"] = stdout_preview
            failure_details["stderr_preview"] = stderr_preview
            self._finalize_attempt(
                task=task,
                status=LlmTaskStatus.FAILED,
                failure_class=classification.failure_class,
                attempt_failure_code=classification.reason_code,
                error_summary=(
                    f"{classification.reason_code}: backend exited with code {execution.exit_code}."
                ),
                execution=execution,
                routing=routing,
                output_path=loaded.output_path,
            )
            if classification.failure_class == FailureClass.BACKEND_TRANSIENT:
                outcome = self._handle_retry_or_fail(
                    task_id=task.task_id,
                    task_attempt=task.attempt,
                    max_attempts=task.max_attempts,
                    failure_class=classification.failure_class,
                    error_summary=(
                        f"{classification.reason_code}: "
                        f"backend exited with code {execution.exit_code}."
                    ),
                    last_exit_code=execution.exit_code,
                    timeout_seconds=task.timeout_seconds,
                    status_on_final=LlmTaskStatus.FAILED,
                    details=failure_details,
                )
                if outcome.retried:
                    summary.retried = 1
                elif outcome.failed:
                    summary.failed = 1
                return

            failed = self.repository.fail_task(
                task_id=task.task_id,
                status=LlmTaskStatus.FAILED,
                failure_class=classification.failure_class,
                error_summary=(
                    f"{classification.reason_code}: backend exited with code {execution.exit_code}."
                ),
                last_exit_code=execution.exit_code,
                details=failure_details,
            )
            if failed:
                summary.failed = 1
            return

        validation = validate_output_contract(
            output_path=Path(manifest.output_result_path),
            allowed_source_ids=allowed_source_ids,
            task_type=task.task_type,
            manifest=manifest,
        )
        if validation.is_valid:
            self.repository.add_task_event(
                task_id=task.task_id,
                event_type="first_pass_validation_passed",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.RUNNING,
                details={
                    "schema_valid": True,
                    "source_mapping_valid": True,
                },
            )
            self._persist_success(
                task=task,
                execution=execution,
                routing=routing,
                loaded=loaded,
                validation_payload=validation.payload,
                task_input_metadata=task_input.metadata,
                summary=summary,
                attempt_failure_code="completed",
            )
            return

        self.repository.add_task_event(
            task_id=task.task_id,
            event_type="first_pass_validation_failed",
            status_from=LlmTaskStatus.RUNNING,
            status_to=LlmTaskStatus.RUNNING,
            details={
                "failure_class": _failure_class_value(validation.failure_class),
                "error_summary": validation.error_summary or "Unknown validation failure.",
            },
        )
        if (
            validation.failure_class == FailureClass.OUTPUT_INVALID_JSON
            and self.backend_capability_mode == "stdout_parser_fallback"
        ):
            parser_recovered = self._try_stdout_parser_recovery(
                task_id=task.task_id,
                output_path=loaded.output_path,
                stdout_path=execution.stdout_path,
                allowed_source_ids=allowed_source_ids,
            )
            if parser_recovered:
                recovered_validation = validate_output_contract(
                    output_path=loaded.output_path,
                    allowed_source_ids=allowed_source_ids,
                    task_type=task.task_type,
                    manifest=manifest,
                )
                if recovered_validation.is_valid:
                    self.repository.add_task_event(
                        task_id=task.task_id,
                        event_type="stdout_parser_recovered",
                        status_from=LlmTaskStatus.RUNNING,
                        status_to=LlmTaskStatus.RUNNING,
                        details={"parser_version": STDOUT_PARSER_VERSION},
                    )
                    self._persist_success(
                        task=task,
                        execution=execution,
                        routing=routing,
                        loaded=loaded,
                        validation_payload=recovered_validation.payload,
                        task_input_metadata=task_input.metadata,
                        summary=summary,
                        attempt_failure_code="stdout_parser_recovered",
                    )
                    return
                validation = recovered_validation

        if validation.failure_class is None or validation.error_summary is None:
            self._finalize_attempt(
                task=task,
                status=LlmTaskStatus.FAILED,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                attempt_failure_code="output_contract_unknown",
                error_summary="Unknown validation failure.",
                execution=execution,
                routing=routing,
                output_path=loaded.output_path,
            )
            failed = self.repository.fail_task(
                task_id=task.task_id,
                status=LlmTaskStatus.FAILED,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary="Unknown validation failure.",
                last_exit_code=execution.exit_code,
            )
            if failed:
                summary.failed = 1
            return

        decision = decide_repair(
            failure_class=validation.failure_class,
            repair_attempted_at=task.repair_attempted_at,
        )
        if decision.should_repair:
            marked = self.repository.mark_repair_attempted(task_id=task.task_id)
            if marked:
                repair_execution = self._execute_backend(
                    task_id=task.task_id,
                    manifest_path=loaded.manifest_path or Path(task.input_manifest_path),
                    task=task,
                    routing=routing,
                    repair_mode=True,
                )
                execution = repair_execution
                if repair_execution.exit_code == 0 and not repair_execution.timed_out:
                    repaired = validate_output_contract(
                        output_path=loaded.output_path,
                        allowed_source_ids=allowed_source_ids,
                        task_type=task.task_type,
                        manifest=manifest,
                    )
                    if repaired.is_valid:
                        self._persist_success(
                            task=task,
                            execution=repair_execution,
                            routing=routing,
                            loaded=loaded,
                            validation_payload=repaired.payload,
                            task_input_metadata=task_input.metadata,
                            summary=summary,
                            attempt_failure_code="repair_recovered",
                        )
                        return

        attempt_failure_code = _attempt_failure_code_from_validation(
            failure_class=validation.failure_class,
            error_summary=validation.error_summary,
        )
        self._finalize_attempt(
            task=task,
            status=LlmTaskStatus.FAILED,
            failure_class=validation.failure_class,
            attempt_failure_code=attempt_failure_code,
            error_summary=validation.error_summary,
            execution=execution,
            routing=routing,
            output_path=loaded.output_path,
        )
        failed = self.repository.fail_task(
            task_id=task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=validation.failure_class,
            error_summary=validation.error_summary,
            last_exit_code=execution.exit_code,
        )
        if failed:
            summary.failed = 1

    def _persist_success(  # noqa: PLR0913
        self,
        *,
        task: LlmTaskView,
        execution: BackendRunResult,
        routing: FrozenRouting,
        loaded: LoadInputsResult,
        validation_payload: dict[str, object] | None,
        task_input_metadata: dict[str, object],
        summary: WorkerRunSummary,
        attempt_failure_code: str,
    ) -> None:
        is_recap = task.task_type.startswith("recap_")

        if is_recap:
            citations: list[OutputCitationSnapshotWrite] = []
        else:
            try:
                citations = self._build_output_citation_snapshots(
                    article_entries=loaded.article_entries,
                    validation_payload=validation_payload,
                )
            except Exception as error:  # noqa: BLE001
                self._finalize_attempt(
                    task=task,
                    status=LlmTaskStatus.FAILED,
                    failure_class=FailureClass.BACKEND_NON_RETRYABLE,
                    attempt_failure_code="citation_snapshot_persist_failed",
                    error_summary=f"Citation snapshot persist failed: {error}",
                    execution=execution,
                    routing=routing,
                    output_path=loaded.output_path,
                )
                failed = self.repository.fail_task(
                    task_id=task.task_id,
                    status=LlmTaskStatus.FAILED,
                    failure_class=FailureClass.BACKEND_NON_RETRYABLE,
                    error_summary=f"Citation snapshot persist failed: {error}",
                    last_exit_code=getattr(execution, "exit_code", None),
                )
                if failed:
                    summary.failed = 1
                return

        # Finalize attempt telemetry FIRST (consistent with failure paths)
        self._finalize_attempt(
            task=task,
            status=LlmTaskStatus.SUCCEEDED,
            failure_class=None,
            attempt_failure_code=attempt_failure_code,
            error_summary=None,
            execution=execution,
            routing=routing,
            output_path=loaded.output_path,
        )

        user_output = (
            None
            if is_recap
            else _build_user_output_upsert(
                task_input_metadata=task_input_metadata,
                validation_payload=validation_payload,
                task_id=task.task_id,
            )
        )

        completed = self.repository.complete_task(
            task_id=task.task_id,
            output_path=str(loaded.output_path),
            citations=citations,
            user_output=user_output,
        )
        if completed:
            summary.succeeded = 1
            return

        self._finalize_attempt(
            task=task,
            status=LlmTaskStatus.CANCELED,
            failure_class=None,
            attempt_failure_code="state_transition_conflict",
            error_summary="Task was canceled concurrently before completion could be committed.",
            execution=execution,
            routing=routing,
            output_path=loaded.output_path,
        )

    def _sleep_with_stop(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop_requested and time.monotonic() < deadline:
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    @contextmanager
    def _signal_handlers(self) -> Iterator[None]:
        if not hasattr(signal, "SIGINT"):
            yield
            return

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        def _handler(signum: int, _: object | None) -> None:
            try:
                name = signal.Signals(signum).name
            except ValueError:
                name = str(signum)
            self._request_stop(signal_name=name)

        try:
            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
            yield
        except ValueError:
            # Signal handlers can only be installed in main thread.
            yield
        finally:
            try:
                signal.signal(signal.SIGINT, original_sigint)
                signal.signal(signal.SIGTERM, original_sigterm)
            except ValueError:
                pass

    def _request_stop(self, *, signal_name: str) -> None:
        self._stop_requested = True
        self._stop_signal_name = signal_name
        if self._current_task_id is None:
            return
        if self._shutdown_task_id == self._current_task_id:
            return
        self._shutdown_task_id = self._current_task_id
        try:
            self.repository.add_task_event(
                task_id=self._current_task_id,
                event_type="shutdown_requested",
                status_from=LlmTaskStatus.RUNNING,
                status_to=LlmTaskStatus.RUNNING,
                details={
                    "signal": signal_name,
                    "graceful_shutdown_seconds": self.graceful_shutdown_seconds,
                },
            )
        except (RuntimeError, ValueError):  # pragma: no cover - best effort
            return

    def _emit_shutdown_completed_if_ready(self) -> None:
        if not self._stop_requested:
            return
        if self._shutdown_completed_emitted:
            return
        if self._shutdown_task_id is None:
            return
        self._shutdown_completed_emitted = True
        try:
            self.repository.add_task_event(
                task_id=self._shutdown_task_id,
                event_type="shutdown_completed",
                status_from=None,
                status_to=None,
                details={
                    "signal": self._stop_signal_name or "unknown",
                    "graceful_shutdown_seconds": self.graceful_shutdown_seconds,
                },
            )
        except (RuntimeError, ValueError):  # pragma: no cover - best effort
            return

    def _execute_backend(
        self,
        *,
        task_id: str,
        manifest_path: Path,
        task: LlmTaskView,
        routing: FrozenRouting,
        repair_mode: bool = False,
    ) -> BackendRunResult:
        execution = self.backend.run(
            BackendRunRequest(
                manifest_path=manifest_path,
                timeout_seconds=task.timeout_seconds,
                agent=routing.agent,
                profile=routing.profile,
                model=routing.model,
                command_template=routing.command_template,
                repair_mode=repair_mode,
                shutdown_requested=lambda: self._stop_requested,
                graceful_shutdown_seconds=self.graceful_shutdown_seconds,
            ),
        )
        self._record_artifacts(task_id=task_id, execution=execution)
        return execution

    def _try_stdout_parser_recovery(
        self,
        *,
        task_id: str,
        output_path: Path,
        stdout_path: Path,
        allowed_source_ids: set[str],
    ) -> bool:
        stdout_text = self._read_text(stdout_path)
        recovered = recover_output_contract_from_stdout(
            stdout_text=stdout_text,
            allowed_source_ids=allowed_source_ids,
        )
        if recovered is None:
            return False
        write_agent_output(output_path, recovered)
        self.repository.add_task_event(
            task_id=task_id,
            event_type="stdout_parser_applied",
            status_from=LlmTaskStatus.RUNNING,
            status_to=LlmTaskStatus.RUNNING,
            details={
                "parser_version": STDOUT_PARSER_VERSION,
                "stdout_chars": len(stdout_text),
            },
        )
        return True

    def _finalize_attempt(  # noqa: PLR0913
        self,
        *,
        task: LlmTaskView,
        status: LlmTaskStatus,
        failure_class: FailureClass | None,
        attempt_failure_code: str | None,
        error_summary: str | None,
        execution: BackendRunResult | None,
        routing: FrozenRouting | None,
        output_path: Path | None,
    ) -> None:
        stdout_text = ""
        stderr_text = ""
        exit_code: int | None = None
        timed_out = False
        if execution is not None:
            stdout_text = self._read_text(execution.stdout_path)
            stderr_text = self._read_text(execution.stderr_path)
            exit_code = execution.exit_code
            timed_out = execution.timed_out

        agent = routing.agent if routing is not None else "unknown"
        model = routing.model if routing is not None else "unknown"
        usage = extract_usage(agent=agent, stdout=stdout_text, stderr=stderr_text)
        estimated_cost = estimate_cost_usd(
            agent=agent,
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )

        self.repository.finalize_task_attempt(
            LlmTaskAttemptFinish(
                task_id=task.task_id,
                attempt_no=task.attempt,
                started_at=task.started_at,
                status=status.value,
                finished_at=utc_now(),
                exit_code=exit_code,
                timed_out=timed_out,
                failure_class=failure_class,
                attempt_failure_code=attempt_failure_code,
                error_summary_sanitized=sanitize_preview(error_summary or ""),
                stdout_preview_sanitized=sanitize_preview(stdout_text),
                stderr_preview_sanitized=sanitize_preview(stderr_text),
                output_chars=_output_chars(
                    output_path=output_path,
                    fallback_stdout=stdout_text,
                ),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                usage_status=usage.usage_status,
                usage_source=usage.usage_source,
                usage_parser_version=usage.parser_version,
                estimated_cost_usd=estimated_cost,
            ),
        )

    def _record_artifacts(self, *, task_id: str, execution: BackendRunResult) -> None:
        stdout_path = getattr(execution, "stdout_path", None)
        stderr_path = getattr(execution, "stderr_path", None)
        if stdout_path is not None and Path(stdout_path).exists():
            self.repository.add_artifact(
                task_id=task_id,
                artifact=self._artifact(kind="stdout_log", path=Path(stdout_path)),
            )
        if stderr_path is not None and Path(stderr_path).exists():
            self.repository.add_artifact(
                task_id=task_id,
                artifact=self._artifact(kind="stderr_log", path=Path(stderr_path)),
            )

    def _artifact(self, *, kind: str, path: Path):
        from news_recap.orchestrator.models import LlmTaskArtifactWrite

        return LlmTaskArtifactWrite(
            kind=kind,
            path=str(path),
            size_bytes=path.stat().st_size if path.exists() else 0,
        )

    def _read_preview(self, path: Path, *, limit: int = 1200) -> str:
        if not path.exists():
            return ""
        text = path.read_text("utf-8", errors="replace")
        compact = text.strip()
        if len(compact) <= limit:
            return compact
        return compact[:limit]

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text("utf-8", errors="replace")

    def _handle_retry_or_fail(  # noqa: PLR0913
        self,
        *,
        task_id: str,
        task_attempt: int,
        max_attempts: int,
        failure_class: FailureClass,
        error_summary: str,
        last_exit_code: int | None,
        timeout_seconds: int,
        status_on_final: LlmTaskStatus,
        details: dict[str, object] | None = None,
    ) -> RetryOutcome:
        retries_left = task_attempt < max_attempts
        if retries_left and failure_class in {
            FailureClass.TIMEOUT,
            FailureClass.BACKEND_TRANSIENT,
        }:
            delay_seconds = self._compute_retry_delay(retry_number=task_attempt)
            retried = self.repository.schedule_retry(
                task_id=task_id,
                run_after=utc_now() + timedelta(seconds=delay_seconds),
                timeout_seconds=timeout_seconds,
                failure_class=failure_class,
                error_summary=error_summary,
                last_exit_code=last_exit_code,
                details=details,
            )
            return RetryOutcome(retried=retried, failed=False)

        failed = self.repository.fail_task(
            task_id=task_id,
            status=status_on_final,
            failure_class=failure_class,
            error_summary=error_summary,
            last_exit_code=last_exit_code,
            details=details,
        )
        return RetryOutcome(retried=False, failed=failed)

    def _compute_retry_delay(self, *, retry_number: int) -> float:
        max_delay = min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2 ** max(retry_number - 1, 0)),
        )
        return self._random.uniform(0, max_delay)

    def _build_output_citation_snapshots(
        self,
        *,
        article_entries: list[ArticleIndexEntry],
        validation_payload: dict[str, object] | None,
    ) -> list[OutputCitationSnapshotWrite]:
        if validation_payload is None:
            raise ValueError("Validation payload is missing for citation snapshot persistence.")

        blocks = _validated_blocks(validation_payload)
        ordered_source_ids = _ordered_source_ids(blocks)
        return _build_citation_writes(
            article_entries=article_entries,
            ordered_source_ids=ordered_source_ids,
        )


def _article_id_from_source_id(source_id: str) -> str | None:
    prefix = "article:"
    if not source_id.startswith(prefix):
        return None
    article_id = source_id[len(prefix) :].strip()
    if not article_id:
        return None
    return article_id


def _failure_class_value(value: FailureClass | None) -> str:
    if value is None:
        return "unknown"
    return value.value


def _command_template_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()  # noqa: S324


def _attempt_failure_code_from_validation(
    *,
    failure_class: FailureClass,
    error_summary: str,
) -> str:
    if failure_class == FailureClass.SOURCE_MAPPING_FAILED:
        return "source_mapping_violation"
    if failure_class == FailureClass.OUTPUT_INVALID_JSON:
        lowered = error_summary.lower()
        if "not found" in lowered:
            return "output_contract_missing_file"
        if "json parse error" in lowered:
            return "output_contract_unreadable"
        return "output_contract_schema_invalid"
    return "validation_failed"


def _output_chars(*, output_path: Path | None, fallback_stdout: str) -> int:
    if output_path is None or not output_path.exists():
        return len(fallback_stdout)
    try:
        payload = json.loads(output_path.read_text("utf-8"))
    except json.JSONDecodeError:
        return len(fallback_stdout)
    if not isinstance(payload, dict):
        return len(fallback_stdout)
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return len(fallback_stdout)
    total = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            total += len(text)
    return total


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _validated_blocks(validation_payload: dict[str, object]) -> list[dict[str, object]]:
    blocks = validation_payload.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError("Validation payload has invalid blocks for citation snapshots.")
    return [block for block in blocks if isinstance(block, dict)]


def _ordered_source_ids(blocks: list[dict[str, object]]) -> list[str]:
    ordered_source_ids: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        source_ids = block.get("source_ids")
        if not isinstance(source_ids, list):
            continue
        for source_id in source_ids:
            if not isinstance(source_id, str):
                continue
            if source_id in seen:
                continue
            seen.add(source_id)
            ordered_source_ids.append(source_id)
    return ordered_source_ids


def _build_citation_writes(
    *,
    article_entries: list[ArticleIndexEntry],
    ordered_source_ids: list[str],
) -> list[OutputCitationSnapshotWrite]:
    entries_by_source_id = {entry.source_id: entry for entry in article_entries}
    citations: list[OutputCitationSnapshotWrite] = []
    for source_id in ordered_source_ids:
        entry = entries_by_source_id.get(source_id)
        if entry is None:
            raise ValueError(f"Source id missing in article index: {source_id}")
        citations.append(
            OutputCitationSnapshotWrite(
                source_id=source_id,
                article_id=_article_id_from_source_id(source_id),
                title=entry.title,
                url=entry.url,
                source=entry.source,
                published_at=_parse_optional_datetime(entry.published_at),
            ),
        )
    return citations


def _build_user_output_upsert(
    *,
    task_input_metadata: dict[str, object],
    validation_payload: dict[str, object] | None,
    task_id: str,
) -> UserOutputUpsert | None:
    target = task_input_metadata.get("output_target")
    if not isinstance(target, dict):
        return None

    kind = target.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        return None

    business_date_raw = target.get("business_date")
    business_date_value: date
    if isinstance(business_date_raw, str) and business_date_raw.strip():
        try:
            business_date_value = date.fromisoformat(business_date_raw)
        except ValueError:
            business_date_value = utc_now().date()
    else:
        business_date_value = utc_now().date()

    blocks_payload = _validated_blocks(validation_payload or {"blocks": []})
    blocks: list[UserOutputBlockWrite] = []
    for index, block in enumerate(blocks_payload):
        block_text = block.get("text", "")
        source_ids_raw = block.get("source_ids", [])
        if not isinstance(source_ids_raw, list):
            source_ids_raw = []
        source_ids = tuple(
            source_id
            for source_id in source_ids_raw
            if isinstance(source_id, str) and source_id.strip()
        )
        blocks.append(
            UserOutputBlockWrite(
                block_order=index,
                text=str(block_text),
                source_ids=source_ids,
            ),
        )

    payload_dict: dict[str, object] = {} if validation_payload is None else validation_payload
    status = target.get("status")
    status_value = str(status) if isinstance(status, str) and status.strip() else "ready"
    return UserOutputUpsert(
        kind=kind.strip(),
        business_date=business_date_value,
        status=status_value,
        payload=payload_dict,
        blocks=blocks,
        story_id=target.get("story_id") if isinstance(target.get("story_id"), str) else None,
        monitor_id=(
            target.get("monitor_id") if isinstance(target.get("monitor_id"), str) else None
        ),
        request_id=(
            target.get("request_id") if isinstance(target.get("request_id"), str) else None
        ),
        task_id=task_id,
        title=target.get("title") if isinstance(target.get("title"), str) else None,
    )


def _validate_required_artifacts(
    *,
    task_type: str,
    manifest: object,
    task_input_metadata: dict[str, object],
) -> str | None:
    output_target = task_input_metadata.get("output_target")
    output_target_routed = isinstance(output_target, dict)
    required_paths_by_task_type: dict[str, tuple[str, ...]] = {
        "story_details": ("story_context_path",),
        "monitor_answer": ("retrieval_context_path",),
    }
    if output_target_routed:
        required_paths_by_task_type = {
            **required_paths_by_task_type,
            "highlights": ("story_context_path",),
            "qa": ("retrieval_context_path",),
        }
    required = required_paths_by_task_type.get(task_type, ())
    for field_name in required:
        field_value = getattr(manifest, field_name, None)
        if not isinstance(field_value, str) or not field_value.strip():
            return (
                f"Input contract error: missing required manifest artifact "
                f"{field_name} for task_type={task_type}."
            )
        if not Path(field_value).exists():
            return (
                f"Input contract error: required manifest artifact does not exist "
                f"({field_name}={field_value})."
            )
    return None
