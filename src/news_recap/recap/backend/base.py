"""Backend interface for orchestrator task execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class BackendRunRequest:
    """Inputs required to execute one task attempt."""

    manifest_path: Path
    timeout_seconds: int
    agent: str
    profile: str
    model: str
    command_template: str
    repair_mode: bool = False
    shutdown_requested: Callable[[], bool] | None = None
    graceful_shutdown_seconds: int | None = None


@dataclass(slots=True)
class BackendRunResult:
    """Execution outcome from backend runner."""

    exit_code: int
    timed_out: bool
    stdout_path: Path
    stderr_path: Path


class LlmBackend(Protocol):
    """Protocol implemented by backend runners."""

    def run(self, request: BackendRunRequest) -> BackendRunResult:
        """Run a task attempt and return execution metadata."""
