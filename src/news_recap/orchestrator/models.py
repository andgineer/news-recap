"""Domain models for orchestrator task queue and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
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
    BILLING_OR_QUOTA = "billing_or_quota"
    ACCESS_OR_AUTH = "access_or_auth"
    MODEL_NOT_AVAILABLE = "model_not_available"
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


@dataclass(slots=True)
class LlmTaskAttemptView:
    """Per-attempt execution telemetry."""

    attempt_id: int
    task_id: str
    user_id: str
    attempt_no: int
    task_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    worker_id: str | None
    agent: str | None
    model: str | None
    profile: str | None
    command_template_hash: str | None
    exit_code: int | None
    timed_out: bool
    failure_class: FailureClass | None
    attempt_failure_code: str | None
    error_summary_sanitized: str | None
    stdout_preview_sanitized: str | None
    stderr_preview_sanitized: str | None
    output_chars: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_status: str | None
    usage_source: str | None
    usage_parser_version: str | None
    estimated_cost_usd: float | None
    created_at: datetime


@dataclass(slots=True)
class LlmTaskAttemptStart:
    """Input to create/update running attempt row at execution start."""

    task_id: str
    attempt_no: int
    task_type: str
    status: str
    started_at: datetime
    worker_id: str | None
    agent: str
    model: str
    profile: str
    command_template_hash: str | None


@dataclass(slots=True)
class LlmTaskAttemptFinish:
    """Input to finalize one attempt row."""

    task_id: str
    attempt_no: int
    started_at: datetime | None
    status: str
    finished_at: datetime
    exit_code: int | None
    timed_out: bool
    failure_class: FailureClass | None
    attempt_failure_code: str | None
    error_summary_sanitized: str | None
    stdout_preview_sanitized: str | None
    stderr_preview_sanitized: str | None
    output_chars: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_status: str | None
    usage_source: str | None
    usage_parser_version: str | None
    estimated_cost_usd: float | None


@dataclass(slots=True)
class SourceCorpusEntry:
    """User-scoped source entry resolved from shared articles via user link."""

    source_id: str
    article_id: str
    title: str
    url: str
    source: str
    published_at: datetime


@dataclass(slots=True)
class OutputCitationSnapshotWrite:
    """Immutable citation snapshot persisted for one output source reference."""

    source_id: str
    article_id: str | None
    title: str
    url: str
    source: str
    published_at: datetime | None


@dataclass(slots=True)
class OutputCitationSnapshotView:
    """Stored citation snapshot row for output rendering and audit."""

    id: int
    task_id: str
    source_id: str
    article_id: str | None
    title: str
    url: str
    source: str
    published_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class StoryDefinitionWrite:
    """Payload for creating/updating a pinned user story definition."""

    story_id: str | None
    name: str
    description: str
    target_language: str = "en"
    priority: int = 100
    enabled: bool = True


@dataclass(slots=True)
class StoryDefinitionView:
    """Stored pinned story definition."""

    story_id: str
    user_id: str
    name: str
    description: str
    target_language: str
    priority: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class StoryAssignmentWrite:
    """One user-scoped article to story assignment."""

    business_date: date
    article_id: str
    story_id: str | None
    story_key: str
    assignment_type: str
    score: float = 0.0


@dataclass(slots=True)
class StoryAssignmentView:
    """Stored article assignment for one business date."""

    article_id: str
    story_id: str | None
    story_key: str
    assignment_type: str
    score: float


@dataclass(slots=True)
class DailyStorySnapshotWrite:
    """Per-day continuity snapshot for one story key."""

    business_date: date
    story_id: str | None
    story_key: str
    title: str
    continuity_key: str | None
    summary: dict[str, Any]


@dataclass(slots=True)
class DailyStorySnapshotView:
    """Stored daily story snapshot."""

    business_date: date
    story_id: str | None
    story_key: str
    title: str
    continuity_key: str | None
    summary: dict[str, Any]
    updated_at: datetime


@dataclass(slots=True)
class MonitorQuestionWrite:
    """Payload for monitor create/update."""

    monitor_id: str | None
    name: str
    prompt: str
    cadence: str = "daily"
    enabled: bool = True


@dataclass(slots=True)
class MonitorQuestionView:
    """Stored monitor definition."""

    monitor_id: str
    user_id: str
    name: str
    prompt: str
    cadence: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class UserOutputBlockWrite:
    """One output block with strict source mapping."""

    block_order: int
    text: str
    source_ids: tuple[str, ...]


@dataclass(slots=True)
class UserOutputUpsert:
    """Upsert payload for stable business output object."""

    kind: str
    business_date: date
    status: str
    payload: dict[str, Any]
    blocks: list[UserOutputBlockWrite]
    story_id: str | None = None
    monitor_id: str | None = None
    request_id: str | None = None
    task_id: str | None = None
    title: str | None = None


@dataclass(slots=True)
class UserOutputView:
    """Stored business output record."""

    output_id: str
    user_id: str
    kind: str
    business_date: date
    status: str
    story_id: str | None
    monitor_id: str | None
    request_id: str | None
    task_id: str | None
    title: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    blocks: list[UserOutputBlockWrite] = field(default_factory=list)


@dataclass(slots=True)
class ReadStateEventWrite:
    """Read/open interaction event against stable output identity."""

    output_id: str
    event_type: str
    output_block_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutputFeedbackWrite:
    """Feedback event attached to output or output block."""

    output_id: str
    feedback_type: str
    output_block_id: int | None = None
    value: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LlmCostAggregateView:
    """Grouped attempt usage/cost summary row."""

    group_key: str
    attempts: int
    succeeded: int
    failed: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    unknown_usage: int
