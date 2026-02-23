"""Base types and checkpoint machinery for the recap pipeline.

Shared types (``RecapPipelineError``, ``PipelineStepResult``, …) live
here so every task module can import them without circular deps.

``TaskLauncher`` is the base class for pipeline steps — see its docstring.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import Digest
from news_recap.recap.storage.pipeline_io import PipelineInput
from news_recap.recap.storage.workdir import TaskWorkdirManager
from news_recap.storage.io import save_msgspec

logger = logging.getLogger(__name__)

_DIGEST_FILENAME = "digest.json"


# ---------------------------------------------------------------------------
# Shared pipeline types
# ---------------------------------------------------------------------------


class RecapPipelineError(RuntimeError):
    """Pipeline step failure."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"Step {step} failed: {message}")
        self.step = step


@dataclass(slots=True)
class PipelineStepResult:
    """Result of a single pipeline step."""

    step_name: str
    task_id: str | None
    status: str
    error: str | None = None


@dataclass(slots=True)
class PipelineRunResult:
    """Result of a complete pipeline run."""

    pipeline_id: str
    business_date: date
    steps: list[PipelineStepResult] = field(default_factory=list)
    digest: dict[str, Any] | None = None
    status: str = "running"
    error: str | None = None


def events_to_resource_files(events: list[dict[str, Any]]) -> dict[str, bytes | str]:
    """Serialize events as individual JSON files for LLM input."""
    resources: dict[str, bytes | str] = {}
    for event in events:
        eid = event.get("event_id", str(uuid4())[:8])
        resources[f"event_{eid}.json"] = json.dumps(event, ensure_ascii=False, indent=2)
    return resources


class StopPipelineError(Exception):
    """Sentinel raised when ``stop_after`` is reached.

    Not an error — the flow catches this and marks the run as completed.
    """


# ---------------------------------------------------------------------------
# Flow context & task launcher
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FlowContext:
    """Shared state passed through all task launchers in a pipeline run."""

    pdir: Path
    workdir_mgr: TaskWorkdirManager
    inp: PipelineInput
    article_map: dict[str, ArticleIndexEntry]
    result: PipelineRunResult
    digest: Digest
    stop_after: str | None = None
    state: dict[str, Any] = field(default_factory=dict)

    def save_checkpoint(self) -> None:
        save_msgspec(self.pdir / _DIGEST_FILENAME, self.digest)


class TaskLauncher:
    """Base for pipeline task launchers — handles checkpoint skip/save and early stopping."""

    name: str

    def __init__(self, ctx: FlowContext) -> None:
        self.ctx = ctx

    @classmethod
    def run(cls, ctx: FlowContext) -> None:
        """Create an instance, handle checkpointing, and call ``execute()``."""
        if cls.name in ctx.digest.completed_phases:
            logger.info("Skipping %s (already completed)", cls.name)
            cls(ctx).restore_state()
            return

        logger.info("Running: %s", cls.name)
        cls(ctx).execute()

        ctx.digest.completed_phases.append(cls.name)
        ctx.save_checkpoint()

        if ctx.stop_after and ctx.stop_after == cls.name:
            raise StopPipelineError(cls.name)

    def execute(self) -> None:
        raise NotImplementedError

    def restore_state(self) -> None:
        """Reconstruct ``ctx.state`` entries from the persisted digest.

        Called when the step is skipped (already completed) so that
        downstream steps that depend on ``ctx.state`` populated by this
        step still work correctly.  Default is a no-op.
        """
