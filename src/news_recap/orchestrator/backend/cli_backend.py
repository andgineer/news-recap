"""Subprocess-based backend runner for CLI agents."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from news_recap.orchestrator.backend.base import BackendRunRequest, BackendRunResult
from news_recap.orchestrator.contracts import read_manifest, read_task_input


class BackendRunError(RuntimeError):
    """Backend execution error with retryability hint."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


class CliAgentBackend:
    """Execute per-task CLI command template resolved by worker routing."""

    def run(self, request: BackendRunRequest) -> BackendRunResult:
        manifest = read_manifest(request.manifest_path)
        task_input = read_task_input(Path(manifest.task_input_path))
        stdout_path = Path(manifest.output_stdout_path)
        stderr_path = Path(manifest.output_stderr_path)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        prompt_file = Path(manifest.workdir) / "input" / "task_prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(task_input.prompt, "utf-8")

        run_args, command_head = _build_run_args(
            command_template=request.command_template,
            model=request.model,
            prompt=task_input.prompt,
            prompt_file=prompt_file,
            manifest_path=request.manifest_path,
        )

        env = os.environ.copy()
        env["NEWS_RECAP_REPAIR_MODE"] = "1" if request.repair_mode else "0"
        env["NEWS_RECAP_LLM_AGENT"] = request.agent
        env["NEWS_RECAP_LLM_MODEL"] = request.model
        env["NEWS_RECAP_LLM_MODEL_PROFILE"] = request.profile

        try:
            with (
                stdout_path.open("w", encoding="utf-8") as stdout_handle,
                stderr_path.open("w", encoding="utf-8") as stderr_handle,
            ):
                completed = subprocess.run(  # noqa: S603
                    run_args,
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
                f"CLI backend command not found: {command_head}",
                transient=False,
            ) from error
        except OSError as error:
            raise BackendRunError(
                f"CLI backend failed to start: {error}",
                transient=True,
            ) from error


def _build_run_args(  # noqa: PLR0913
    *,
    command_template: str,
    model: str,
    prompt: str,
    prompt_file: Path,
    manifest_path: Path,
) -> tuple[str | list[str], str]:
    stripped = command_template.strip()
    if not stripped:
        raise BackendRunError("CLI backend command template is empty.", transient=False)

    try:
        if os.name == "nt":
            rendered = stripped.format(
                model=subprocess.list2cmdline([model]),
                prompt=subprocess.list2cmdline([prompt]),
                prompt_file=subprocess.list2cmdline([str(prompt_file)]),
                task_manifest=subprocess.list2cmdline([str(manifest_path)]),
            ).strip()
            if not rendered:
                raise BackendRunError(
                    "CLI backend command template rendered empty command.",
                    transient=False,
                )
            command_head = rendered.split(maxsplit=1)[0]
            return rendered, command_head

        rendered = stripped.format(
            model=shlex.quote(model),
            prompt=shlex.quote(prompt),
            prompt_file=shlex.quote(str(prompt_file)),
            task_manifest=shlex.quote(str(manifest_path)),
        )
    except KeyError as error:
        raise BackendRunError(
            f"Unsupported command template placeholder: {error}",
            transient=False,
        ) from error

    argv = shlex.split(rendered)
    if not argv:
        raise BackendRunError(
            "CLI backend command template rendered empty command.",
            transient=False,
        )
    return argv, argv[0]
