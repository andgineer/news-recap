"""Domain models for intelligence layer: stories, monitors, outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class SourceCorpusEntry:
    """User-scoped source entry resolved from shared articles via user link."""

    source_id: str
    article_id: str
    title: str
    url: str
    source: str
    published_at: datetime
    clean_text: str = ""


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
