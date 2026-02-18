"""Subprocess-based backend runner for CLI agents."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from news_recap.orchestrator.backend.base import BackendRunRequest, BackendRunResult
from news_recap.orchestrator.contracts import read_manifest


class BackendRunError(RuntimeError):
    """Backend execution error with retryability hint."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(slots=True)
class CliAgentBackend:
    """Execute configured CLI command with task manifest."""

    command: str

    def run(self, request: BackendRunRequest) -> BackendRunResult:
        manifest = read_manifest(request.manifest_path)
        stdout_path = Path(manifest.output_stdout_path)
        stderr_path = Path(manifest.output_stderr_path)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        argv = shlex.split(self.command)
        if not argv:
            raise BackendRunError("CLI backend command is empty.", transient=False)
        argv.extend(["--task-manifest", str(request.manifest_path)])

        env = os.environ.copy()
        env["NEWS_RECAP_REPAIR_MODE"] = "1" if request.repair_mode else "0"

        try:
            with (
                stdout_path.open("w", encoding="utf-8") as stdout_handle,
                stderr_path.open(
                    "w",
                    encoding="utf-8",
                ) as stderr_handle,
            ):
                completed = subprocess.run(  # noqa: S603
                    argv,
                    check=False,
                    env=env,
                    timeout=request.timeout_seconds,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                )
            return BackendRunResult(
                exit_code=completed.returncode,
                timed_out=False,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except subprocess.TimeoutExpired:
            return BackendRunResult(
                exit_code=124,
                timed_out=True,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except FileNotFoundError as error:
            raise BackendRunError(
                f"CLI backend command not found: {argv[0]}",
                transient=False,
            ) from error
        except OSError as error:
            raise BackendRunError(
                f"CLI backend failed to start: {error}",
                transient=True,
            ) from error
