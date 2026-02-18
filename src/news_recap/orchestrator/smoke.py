"""Lightweight smoke checks for external CLI LLM agents."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(slots=True)
class AgentSmokeSpec:
    """One agent smoke-check configuration."""

    agent: str
    executable: str
    command_template: str | None = None


@dataclass(slots=True)
class AgentSmokeResult:
    """One agent smoke-check result."""

    agent: str
    executable: str
    available: bool
    probe_ok: bool
    run_ok: bool
    skipped_run: bool
    error: str | None
    stdout_preview: str
    stderr_preview: str


def run_smoke_checks(
    *,
    specs: list[AgentSmokeSpec],
    prompt: str,
    expect_substring: str,
    timeout_seconds: int,
) -> list[AgentSmokeResult]:
    """Run probe + synthetic prompt checks for configured agents."""

    results: list[AgentSmokeResult] = []
    for spec in specs:
        executable_path = shutil.which(spec.executable)
        if executable_path is None:
            results.append(
                AgentSmokeResult(
                    agent=spec.agent,
                    executable=spec.executable,
                    available=False,
                    probe_ok=False,
                    run_ok=False,
                    skipped_run=True,
                    error=f"Executable not found in PATH: {spec.executable}",
                    stdout_preview="",
                    stderr_preview="",
                ),
            )
            continue

        probe_ok, probe_error, probe_stdout, probe_stderr = _run_probe(
            executable=spec.executable,
            timeout_seconds=timeout_seconds,
        )
        if not probe_ok:
            results.append(
                AgentSmokeResult(
                    agent=spec.agent,
                    executable=spec.executable,
                    available=True,
                    probe_ok=False,
                    run_ok=False,
                    skipped_run=True,
                    error=probe_error,
                    stdout_preview=probe_stdout,
                    stderr_preview=probe_stderr,
                ),
            )
            continue

        if spec.command_template is None or not spec.command_template.strip():
            results.append(
                AgentSmokeResult(
                    agent=spec.agent,
                    executable=spec.executable,
                    available=True,
                    probe_ok=True,
                    run_ok=False,
                    skipped_run=True,
                    error="No run command configured.",
                    stdout_preview=probe_stdout,
                    stderr_preview=probe_stderr,
                ),
            )
            continue

        run_ok, run_error, run_stdout, run_stderr = _run_synthetic_task(
            command_template=spec.command_template,
            prompt=prompt,
            expect_substring=expect_substring,
            timeout_seconds=timeout_seconds,
        )
        results.append(
            AgentSmokeResult(
                agent=spec.agent,
                executable=spec.executable,
                available=True,
                probe_ok=True,
                run_ok=run_ok,
                skipped_run=False,
                error=run_error,
                stdout_preview=run_stdout,
                stderr_preview=run_stderr,
            ),
        )

    return results


def _run_probe(*, executable: str, timeout_seconds: int) -> tuple[bool, str | None, str, str]:
    for probe_args in ([executable, "--version"], [executable, "--help"]):
        try:
            completed = subprocess.run(  # noqa: S603
                probe_args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, "Probe timed out.", "", ""
        except OSError as error:
            return False, f"Probe failed to start: {error}", "", ""

        stdout = _truncate(completed.stdout)
        stderr = _truncate(completed.stderr)
        if completed.returncode == 0:
            return True, None, stdout, stderr

    return False, "Probe command failed.", stdout, stderr


def _run_synthetic_task(
    *,
    command_template: str,
    prompt: str,
    expect_substring: str,
    timeout_seconds: int,
) -> tuple[bool, str | None, str, str]:
    with TemporaryDirectory(prefix="news-recap-smoke-") as temp_dir:
        prompt_file = Path(temp_dir) / "prompt.txt"
        prompt_file.write_text(prompt, "utf-8")

        has_prompt_placeholder = "{prompt}" in command_template
        has_prompt_file_placeholder = "{prompt_file}" in command_template
        rendered = command_template.format(
            prompt=shlex.quote(prompt),
            prompt_file=shlex.quote(str(prompt_file)),
        )
        argv = shlex.split(rendered)
        if not argv:
            return False, "Configured command is empty.", "", ""
        if not has_prompt_placeholder and not has_prompt_file_placeholder:
            argv.append(prompt)

        try:
            completed = subprocess.run(  # noqa: S603
                argv,
                check=False,
                capture_output=True,
                text=True,
                input=prompt,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, "Synthetic task timed out.", "", ""
        except OSError as error:
            return False, f"Synthetic task failed to start: {error}", "", ""

        stdout = _truncate(completed.stdout)
        stderr = _truncate(completed.stderr)
        if completed.returncode != 0:
            return False, f"Synthetic task exit code={completed.returncode}", stdout, stderr
        if expect_substring not in completed.stdout:
            return (
                False,
                f"Synthetic output missing expected substring: {expect_substring!r}",
                stdout,
                stderr,
            )
        return True, None, stdout, stderr


def _truncate(value: str, *, limit: int = 240) -> str:
    compact = value.strip().replace("\n", " ")
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
