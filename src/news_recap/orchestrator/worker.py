"""Queue worker that executes CLI-backed LLM tasks."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from news_recap.ingestion.storage.common import utc_now
from news_recap.orchestrator.backend import (
    BackendRunError,
    BackendRunRequest,
    CliAgentBackend,
)
from news_recap.orchestrator.contracts import (
    ArticleIndexEntry,
    read_articles_index,
    read_manifest,
    read_task_input,
)
from news_recap.orchestrator.failure_classifier import classify_backend_failure
from news_recap.orchestrator.models import (
    FailureClass,
    LlmTaskStatus,
    LlmTaskView,
    OutputCitationSnapshotWrite,
)
from news_recap.orchestrator.repair import decide_repair
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import (
    FrozenRouting,
    RoutingDefaults,
    resolve_routing_for_execution,
)
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
        self._random = random.Random()  # noqa: S311

    def run_once(self) -> WorkerRunSummary:  # noqa: C901, PLR0911, PLR0912, PLR0915
        """Process at most one task from the queue."""

        summary = WorkerRunSummary()
        task = self.repository.claim_next_ready_task(worker_id=self.worker_id)
        if task is None:
            summary.idle_polls = 1
            return summary

        summary.processed = 1
        manifest_path = Path(task.input_manifest_path)
        try:
            manifest = read_manifest(manifest_path)
            task_input = read_task_input(Path(manifest.task_input_path))
            article_entries = read_articles_index(Path(manifest.articles_index_path))
        except Exception as error:  # noqa: BLE001
            failed = self.repository.fail_task(
                task_id=task.task_id,
                status=LlmTaskStatus.FAILED,
                failure_class=FailureClass.INPUT_CONTRACT_ERROR,
                error_summary=f"Input contract error: {error}",
                last_exit_code=None,
            )
            if failed:
                summary.failed = 1
            return summary

        allowed_source_ids = {entry.source_id for entry in article_entries}
        routing, fallback_reason = resolve_routing_for_execution(
            task_input=task_input,
            task_type=task.task_type,
            defaults=self.routing_defaults,
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
                manifest_path=manifest_path,
                task=task,
                routing=routing,
            )
        except BackendRunError as error:
            failure_class = (
                FailureClass.BACKEND_TRANSIENT
                if error.transient
                else FailureClass.BACKEND_NON_RETRYABLE
            )
            failure_details: dict[str, object] = {
                "reason_code": f"{routing.agent}_backend_run_error",
                "resolved_agent": routing.agent,
                "resolved_model": routing.model,
                "resolved_profile": routing.profile,
            }
            if failure_class == FailureClass.BACKEND_TRANSIENT:
                outcome = self._handle_retry_or_fail(
                    task_id=task.task_id,
                    task_attempt=task.attempt,
                    max_attempts=task.max_attempts,
                    failure_class=failure_class,
                    error_summary=str(error),
                    last_exit_code=None,
                    timeout_seconds=task.timeout_seconds,
                    status_on_final=LlmTaskStatus.FAILED,
                    details=failure_details,
                )
                if outcome.retried:
                    summary.retried = 1
                elif outcome.failed:
                    summary.failed = 1
                return summary

            failed = self.repository.fail_task(
                task_id=task.task_id,
                status=LlmTaskStatus.FAILED,
                failure_class=failure_class,
                error_summary=str(error),
                last_exit_code=None,
                details=failure_details,
            )
            if failed:
                summary.failed = 1
            return summary
        if execution.timed_out:
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
            return summary

        if execution.exit_code != 0:
            stdout_preview = self._read_preview(execution.stdout_path)
            stderr_preview = self._read_preview(execution.stderr_path)
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
                return summary

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
            return summary

        validation = validate_output_contract(
            output_path=Path(manifest.output_result_path),
            allowed_source_ids=allowed_source_ids,
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
            try:
                citations = self._build_output_citation_snapshots(
                    article_entries=article_entries,
                    validation_payload=validation.payload,
                )
            except Exception as error:  # noqa: BLE001
                failed = self.repository.fail_task(
                    task_id=task.task_id,
                    status=LlmTaskStatus.FAILED,
                    failure_class=FailureClass.BACKEND_NON_RETRYABLE,
                    error_summary=f"Citation snapshot persist failed: {error}",
                    last_exit_code=execution.exit_code,
                )
                if failed:
                    summary.failed = 1
                return summary
            completed = self.repository.complete_task(
                task_id=task.task_id,
                output_path=manifest.output_result_path,
                citations=citations,
            )
            if completed:
                summary.succeeded = 1
            return summary

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
        if validation.failure_class is None or validation.error_summary is None:
            failed = self.repository.fail_task(
                task_id=task.task_id,
                status=LlmTaskStatus.FAILED,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary="Unknown validation failure.",
                last_exit_code=execution.exit_code,
            )
            if failed:
                summary.failed = 1
            return summary

        decision = decide_repair(
            failure_class=validation.failure_class,
            repair_attempted_at=task.repair_attempted_at,
        )
        if decision.should_repair:
            marked = self.repository.mark_repair_attempted(task_id=task.task_id)
            if marked:
                repair_execution = self._execute_backend(
                    task_id=task.task_id,
                    manifest_path=manifest_path,
                    task=task,
                    routing=routing,
                    repair_mode=True,
                )
                if repair_execution.exit_code == 0 and not repair_execution.timed_out:
                    repaired = validate_output_contract(
                        output_path=Path(manifest.output_result_path),
                        allowed_source_ids=allowed_source_ids,
                    )
                    if repaired.is_valid:
                        try:
                            citations = self._build_output_citation_snapshots(
                                article_entries=article_entries,
                                validation_payload=repaired.payload,
                            )
                        except Exception as error:  # noqa: BLE001
                            failed = self.repository.fail_task(
                                task_id=task.task_id,
                                status=LlmTaskStatus.FAILED,
                                failure_class=FailureClass.BACKEND_NON_RETRYABLE,
                                error_summary=f"Citation snapshot persist failed: {error}",
                                last_exit_code=repair_execution.exit_code,
                            )
                            if failed:
                                summary.failed = 1
                            return summary
                        completed = self.repository.complete_task(
                            task_id=task.task_id,
                            output_path=manifest.output_result_path,
                            citations=citations,
                        )
                        if completed:
                            summary.succeeded = 1
                        return summary

        failed = self.repository.fail_task(
            task_id=task.task_id,
            status=LlmTaskStatus.FAILED,
            failure_class=validation.failure_class,
            error_summary=validation.error_summary,
            last_exit_code=execution.exit_code,
        )
        if failed:
            summary.failed = 1
        return summary

    def run_loop(self, *, max_tasks: int | None = None) -> WorkerRunSummary:
        """Run worker loop until queue is idle or max_tasks reached."""

        aggregate = WorkerRunSummary()
        while True:
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
                return aggregate
            if max_tasks is None and self.poll_interval_seconds > 0:
                time.sleep(self.poll_interval_seconds)

    def _execute_backend(
        self,
        *,
        task_id: str,
        manifest_path: Path,
        task: LlmTaskView,
        routing: FrozenRouting,
        repair_mode: bool = False,
    ):
        execution = self.backend.run(
            BackendRunRequest(
                manifest_path=manifest_path,
                timeout_seconds=task.timeout_seconds,
                agent=routing.agent,
                profile=routing.profile,
                model=routing.model,
                command_template=routing.command_template,
                repair_mode=repair_mode,
            ),
        )
        self._record_artifacts(task_id=task_id, execution=execution)
        return execution

    def _record_artifacts(self, *, task_id: str, execution: object) -> None:
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
