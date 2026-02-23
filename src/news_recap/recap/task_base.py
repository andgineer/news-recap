"""Base class for recap pipeline task launchers.

Each pipeline step (classify, enrich, group, …) subclasses ``TaskLauncher``
and implements ``execute()``.  The base ``run()`` classmethod handles:

* **Skip** — when the task name is already in ``digest.completed_phases``.
* **Checkpoint** — persists the digest after a successful execution.
* **Early stop** — raises ``StopPipeline`` when ``ctx.stop_after`` matches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import Digest
from news_recap.recap.pipeline_io import PipelineInput
from news_recap.recap.runner import PipelineRunResult
from news_recap.recap.workdir import TaskWorkdirManager
from news_recap.storage.io import save_msgspec

logger = logging.getLogger(__name__)

_DIGEST_FILENAME = "digest.json"


class StopPipelineError(Exception):
    """Sentinel raised when ``stop_after`` is reached.

    Not an error — the flow catches this and marks the run as completed.
    """


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
            return

        logger.info("Running: %s", cls.name)
        cls(ctx).execute()

        ctx.digest.completed_phases.append(cls.name)
        ctx.save_checkpoint()

        if ctx.stop_after and ctx.stop_after == cls.name:
            raise StopPipelineError(cls.name)

    def execute(self) -> None:
        raise NotImplementedError
