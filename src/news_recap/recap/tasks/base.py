"""Base types and checkpoint machinery for the recap pipeline.

Shared types (``RecapPipelineError``, ``FlowContext``, …) live here so
every task module can import them without circular deps.

``TaskLauncher`` is the base class for pipeline steps — see its docstring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import Digest
from news_recap.recap.pipeline_setup import _DIGEST_FILENAME
from news_recap.recap.storage.pipeline_io import PipelineInput
from news_recap.recap.storage.workdir import TaskWorkdirManager
from news_recap.storage.io import save_msgspec

if TYPE_CHECKING:
    from news_recap.recap.agents.concurrency import ConcurrencyController
    from news_recap.recap.agents.transport import LLMTransport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared pipeline types
# ---------------------------------------------------------------------------


class RecapPipelineError(RuntimeError):
    """Pipeline step failure."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"Step {step} failed: {message}")
        self.step = step


_STDOUT_SNIPPET_CHARS = 500


def log_parse_failure(label: str, raw_stdout: str, *, log: logging.Logger) -> None:
    """Log a truncated snippet of raw agent stdout for post-mortem diagnostics."""
    snippet = raw_stdout[:_STDOUT_SNIPPET_CHARS].replace("\n", "\\n")
    log.error(
        "%s parse failure — raw agent stdout (first %d chars): %s",
        label,
        _STDOUT_SNIPPET_CHARS,
        snippet,
    )


def read_agent_stdout(stdout_path: Path, step_name: str) -> str:
    """Read agent stdout, raising ``RecapPipelineError`` if the file is missing or empty."""
    if not stdout_path.exists():
        raise RecapPipelineError(step_name, f"stdout not found: {stdout_path}")
    text = stdout_path.read_text("utf-8")
    if not text.strip():
        raise RecapPipelineError(step_name, "stdout is empty")
    return text


def run_single_agent(
    ctx: FlowContext,
    step_name: str,
    prompt: str,
    batch: int | None = None,
) -> Path:
    """Materialize a task, run the agent, and return the stdout path.

    Encapsulates the materialize → invoke → locate stdout pattern used
    by single-call phases (oneshot_digest batches, merge_sections, refine_layout).
    """
    from news_recap.recap.agents.ai_agent import run_ai_agent
    from news_recap.recap.storage.workdir import materialize_step

    tid = materialize_step(
        ctx.workdir_mgr,
        ctx.inp,
        step_name=step_name,
        prompt=prompt,
        batch=batch,
    )
    tid = run_ai_agent(
        pipeline_dir=str(ctx.pdir),
        step_name=step_name,
        task_id=tid,
        transport=ctx.transport,
        concurrency_controller=ctx.cc,
    )
    return ctx.pdir / tid / "output" / "agent_stdout.log"


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
    digest: Digest
    stop_after: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    transport: LLMTransport | None = None
    cc: ConcurrencyController | None = None

    def save_checkpoint(self) -> None:
        save_msgspec(self.pdir / _DIGEST_FILENAME, self.digest)


class TaskLauncher:
    """Base for pipeline task launchers — handles checkpoint skip/save and early stopping.

    Subclasses set ``fully_completed = False`` in ``execute()`` to
    prevent the phase from being added to ``completed_phases``.  On the
    next pipeline run the phase will re-execute, giving it a chance to
    process remaining work.  Partial results are still saved to the
    digest via ``save_checkpoint()``.
    """

    name: str
    fully_completed: bool

    def __init__(self, ctx: FlowContext) -> None:
        self.ctx = ctx
        self.fully_completed = True

    @classmethod
    def run(cls, ctx: FlowContext) -> None:
        """Create an instance, handle checkpointing, and call ``execute()``."""
        if cls.name in ctx.digest.completed_phases:
            logger.info("Skipping %s (already completed)", cls.name)
            cls(ctx).restore_state()
            if ctx.stop_after and ctx.stop_after == cls.name:
                raise StopPipelineError(cls.name)
            return

        logger.info("── %s ──", cls.name)
        instance = cls(ctx)
        instance.execute()

        if instance.fully_completed:
            ctx.digest.completed_phases.append(cls.name)
        else:
            logger.warning("%s partially completed — will retry on next run", cls.name)
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
