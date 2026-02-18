"""Domain models for orchestrator task queue and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class LlmTaskStatus(str, Enum):
    """Durable task lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELED = "canceled"


class FailureClass(str, Enum):
    """Normalized failure classes used by retry policy."""

    TIMEOUT = "timeout"
    BACKEND_TRANSIENT = "backend_transient"
    BACKEND_NON_RETRYABLE = "backend_non_retryable"
    OUTPUT_INVALID_JSON = "output_invalid_json"
    SOURCE_MAPPING_FAILED = "source_mapping_failed"
    INPUT_CONTRACT_ERROR = "input_contract_error"


@dataclass(slots=True)
class LlmTaskCreate:
    """Input payload for enqueuing an LLM task."""

    task_type: str
    task_id: str | None = None
    priority: int = 100
    max_attempts: int = 3
    timeout_seconds: int = 600
    run_after: datetime | None = None
    input_manifest_path: str = ""
    output_path: str | None = None


@dataclass(slots=True)
class LlmTaskView:
    """Readable task view for CLI and worker logic."""

    task_id: str
    user_id: str
    task_type: str
    priority: int
    status: LlmTaskStatus
    attempt: int
    max_attempts: int
    timeout_seconds: int
    run_after: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    failure_class: FailureClass | None
    last_exit_code: int | None
    repair_attempted_at: datetime | None
    worker_id: str | None
    input_manifest_path: str
    output_path: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class LlmTaskEventView:
    """Task event entry for audit trail."""

    event_id: int
    task_id: str
    event_type: str
    status_from: LlmTaskStatus | None
    status_to: LlmTaskStatus | None
    created_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LlmTaskArtifactWrite:
    """Artifact metadata captured during execution."""

    kind: str
    path: str
    size_bytes: int
    checksum_sha256: str | None = None


@dataclass(slots=True)
class LlmTaskDetails:
    """Task details with event stream."""

    task: LlmTaskView
    events: list[LlmTaskEventView]
