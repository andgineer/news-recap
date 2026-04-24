"""Shared pipeline exception types.

Extracted here to break the circular dependency between
``recap.agents.ai_agent`` and ``recap.tasks.base``.
"""

from __future__ import annotations


class RecapPipelineError(RuntimeError):
    """Pipeline step failure."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"Step {step} failed: {message}")
        self.step = step


class StopPipelineError(Exception):
    """Sentinel raised when ``stop_after`` is reached.

    Not an error — the flow catches this and marks the run as completed.
    """
