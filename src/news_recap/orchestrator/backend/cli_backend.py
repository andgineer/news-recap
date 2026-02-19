"""Subprocess-based backend runner for CLI agents."""

from __future__ import annotations

import os
import shlex
import string
import subprocess
import time
from pathlib import Path

from news_recap.orchestrator.backend.base import BackendRunRequest, BackendRunResult
from news_recap.orchestrator.contracts import (
    TaskManifest,
    read_manifest,
    read_task_input,
)


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

        enriched_prompt = _build_enriched_prompt(
            base_prompt=task_input.prompt,
            manifest=manifest,
        )

        prompt_file = Path(manifest.workdir) / "input" / "task_prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(enriched_prompt, "utf-8")

        run_args, command_head = _build_run_args(
            command_template=request.command_template,
            model=request.model,
            prompt=enriched_prompt,
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
                return _run_subprocess_with_shutdown(
                    run_args=run_args,
                    env=env,
                    timeout_seconds=request.timeout_seconds,
                    stdout_handle=stdout_handle,
                    stderr_handle=stderr_handle,
                    shutdown_requested=request.shutdown_requested,
                    graceful_shutdown_seconds=request.graceful_shutdown_seconds,
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


_OUTPUT_SCHEMA_EXAMPLE = """\
{
  "blocks": [
    {
      "text": "<highlight or analysis text>",
      "source_ids": ["article:<id>"]
    }
  ],
  "metadata": {}
}"""


def _build_enriched_prompt(
    *,
    base_prompt: str,
    manifest: TaskManifest,
) -> str:
    """Wrap the task prompt with manifest path and output contract."""

    manifest_path = f"{manifest.workdir}/meta/task_manifest.json"

    return (
        f"{base_prompt}\n"
        f"\n"
        f"Your task manifest is at: {manifest_path}\n"
        f"\n"
        f"Steps:\n"
        f"1. Read the manifest JSON — it contains paths to all input/output files.\n"
        f"2. Read articles_index_path from the manifest — each article has a source_id,\n"
        f"   title, url, and source. Use these as your source material.\n"
        f"3. Write the result to output_result_path from the manifest.\n"
        f"4. The output file must follow this JSON schema exactly:\n"
        f"{_OUTPUT_SCHEMA_EXAMPLE}\n"
        f"5. Each block.source_ids must only reference source_ids from articles_index.\n"
        f"\n"
        f"Do not search the web. Write only the output JSON file.\n"
    )


def _build_run_args(  # noqa: PLR0913
    *,
    command_template: str,
    model: str,
    prompt: str,
    prompt_file: Path,
    manifest_path: Path,
    os_name: str | None = None,
) -> tuple[str | list[str], str]:
    stripped = command_template.strip()
    if not stripped:
        raise BackendRunError("CLI backend command template is empty.", transient=False)
    if "{prompt}" not in stripped:
        raise BackendRunError(
            "CLI backend command template must include {prompt}.",
            transient=False,
        )

    current_os_name = os_name or os.name
    try:
        if current_os_name == "nt":
            rendered = _render_windows_command_template(
                template=stripped,
                values={
                    "model": model,
                    "prompt": prompt,
                    "prompt_file": str(prompt_file),
                    "task_manifest": str(manifest_path),
                },
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


def _render_windows_command_template(*, template: str, values: dict[str, str]) -> str:
    formatter = string.Formatter()
    rendered_parts: list[str] = []
    in_double_quotes = False

    for literal_text, field_name, format_spec, conversion in formatter.parse(template):
        rendered_parts.append(literal_text)
        in_double_quotes = _advance_windows_quote_state(literal_text, in_double_quotes)
        if field_name is None:
            continue

        try:
            value = values[field_name]
        except KeyError as error:
            raise KeyError(field_name) from error

        value_text = _apply_string_conversion(value, conversion, format_spec)
        if in_double_quotes:
            rendered_parts.append(_escape_windows_embedded_quote_value(value_text))
            continue

        rendered_parts.append(subprocess.list2cmdline([value_text]))

    return "".join(rendered_parts)


def _apply_string_conversion(
    value: str,
    conversion: str | None,
    format_spec: str | None,
) -> str:
    converted: str
    if conversion == "r":
        converted = repr(value)
    elif conversion == "a":
        converted = ascii(value)
    elif conversion in (None, "", "s"):
        converted = str(value)
    else:
        raise ValueError(f"Unsupported format conversion: !{conversion}")

    if format_spec:
        return format(converted, format_spec)
    return converted


def _advance_windows_quote_state(literal_text: str, in_double_quotes: bool) -> bool:
    for index, char in enumerate(literal_text):
        if char != '"':
            continue
        backslashes = 0
        scan_index = index - 1
        while scan_index >= 0 and literal_text[scan_index] == "\\":
            backslashes += 1
            scan_index -= 1
        if backslashes % 2 == 1:
            continue
        in_double_quotes = not in_double_quotes
    return in_double_quotes


def _escape_windows_embedded_quote_value(value: str) -> str:
    return value.replace('"', '\\"')


def _run_subprocess_with_shutdown(  # noqa: PLR0913
    *,
    run_args: str | list[str],
    env: dict[str, str],
    timeout_seconds: int,
    stdout_handle,
    stderr_handle,
    shutdown_requested,
    graceful_shutdown_seconds: int | None,
    stdout_path: Path,
    stderr_path: Path,
) -> BackendRunResult:
    process = subprocess.Popen(  # noqa: S603
        run_args,
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    start_monotonic = time.monotonic()
    shutdown_deadline: float | None = None
    graceful_seconds = max(0, graceful_shutdown_seconds or 0)

    while True:
        returncode = process.poll()
        if returncode is not None:
            return BackendRunResult(
                exit_code=returncode,
                timed_out=False,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

        now = time.monotonic()
        if now - start_monotonic >= timeout_seconds:
            _terminate_process(process)
            return BackendRunResult(
                exit_code=124,
                timed_out=True,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

        if shutdown_requested is not None and shutdown_requested():
            if shutdown_deadline is None:
                shutdown_deadline = now + graceful_seconds
            if now >= shutdown_deadline:
                _terminate_process(process)
                return BackendRunResult(
                    exit_code=124,
                    timed_out=True,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )

        time.sleep(0.1)


def _terminate_process(process: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            return
        process.wait(timeout=2)
