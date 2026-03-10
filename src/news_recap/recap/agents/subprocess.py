"""Generic subprocess execution and command-template rendering.

Used by ``task_ai_agent`` to run CLI agents but has no knowledge of
AI agents, routing, or prompt contracts.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import string
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class SubprocessError(RuntimeError):
    """Subprocess launch/template error with retryability hint."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(slots=True)
class SubprocessResult:
    """Outcome of a subprocess execution."""

    exit_code: int
    timed_out: bool
    stdout_path: Path
    stderr_path: Path


# ---------------------------------------------------------------------------
# Command template rendering
# ---------------------------------------------------------------------------


def build_run_args(
    command_template: str,
    *,
    os_name: str | None = None,
    **values: str | Path,
) -> tuple[str | list[str], str]:
    """Render *command_template* with **values** and return ``(run_args, command_head)``.

    All keyword arguments (except *os_name*) are substituted into the
    template.  ``Path`` values are shell-quoted on Unix (using POSIX
    notation); ``str`` values are inserted raw because they may contain
    multi-word CLI argument fragments (e.g. ``--model gpt-5.2 -c effort=low``).
    On Windows the existing ``list2cmdline`` quoting applies to all values.
    """
    stripped = command_template.strip()
    if not stripped:
        raise SubprocessError("Command template is empty.", transient=False)

    current_os_name = os_name or os.name
    str_values = {k: v.as_posix() if isinstance(v, Path) else str(v) for k, v in values.items()}
    try:
        if current_os_name == "nt":
            rendered = _render_windows_command_template(
                template=stripped,
                values=str_values,
            ).strip()
            if not rendered:
                raise SubprocessError(
                    "Command template rendered empty command.",
                    transient=False,
                )
            command_head = rendered.split(maxsplit=1)[0]
            return rendered, command_head

        unix_values = {
            k: shlex.quote(v.as_posix()) if isinstance(v, Path) else str(v)
            for k, v in values.items()
        }
        rendered = stripped.format(**unix_values)
    except KeyError as error:
        raise SubprocessError(
            f"Unsupported command template placeholder: {error}",
            transient=False,
        ) from error

    argv = shlex.split(rendered)
    if not argv:
        raise SubprocessError("Command template rendered empty command.", transient=False)
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


# ---------------------------------------------------------------------------
# Subprocess execution
# ---------------------------------------------------------------------------


_STDERR_POLL_INTERVAL = 5.0
_HEARTBEAT_INTERVAL = 60.0

_NOTABLE_RE = re.compile(
    r"quota|rate.?limit|429|too many requests|overloaded|retrying|"
    r"Operation cancelled|exhausted.*capacity|"
    r"credit balance|insufficient.{0,20}(funds|credits|balance)",
    re.IGNORECASE,
)


def run_subprocess(  # noqa: PLR0913
    *,
    run_args: str | list[str],
    env: dict[str, str],
    cwd: Path | None = None,
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
    log_label: str = "",
    stop_event: threading.Event | None = None,
) -> SubprocessResult:
    """Run a subprocess with timeout, capturing stdout/stderr to files."""
    with (
        stdout_path.open("w", encoding="utf-8") as stdout_handle,
        stderr_path.open("w", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(  # noqa: S603
            run_args,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        start_monotonic = time.monotonic()
        last_output_check = start_monotonic
        last_heartbeat = start_monotonic
        stderr_offset = 0
        stdout_offset = 0

        try:
            while True:
                returncode = process.poll()
                if returncode is not None:
                    return SubprocessResult(
                        exit_code=returncode,
                        timed_out=False,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    )

                now = time.monotonic()
                elapsed = now - start_monotonic

                if stop_event is not None and stop_event.is_set():
                    _terminate_process(process)
                    return SubprocessResult(
                        exit_code=130,
                        timed_out=False,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    )

                if elapsed >= timeout_seconds:
                    _terminate_process(process)
                    return SubprocessResult(
                        exit_code=124,
                        timed_out=True,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    )

                if now - last_output_check >= _STDERR_POLL_INTERVAL:
                    stderr_offset = _check_output(
                        stderr_path,
                        stderr_offset,
                        log_label,
                        "stderr",
                    )
                    stdout_offset = _check_output(
                        stdout_path,
                        stdout_offset,
                        log_label,
                        "stdout",
                    )
                    last_output_check = now

                if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    remaining = timeout_seconds - int(elapsed)
                    stdout_size = _file_size(stdout_path)
                    stderr_size = _file_size(stderr_path)
                    logger.info(
                        "[%s] still running (%ds elapsed, %ds until timeout,"
                        " stdout=%d bytes, stderr=%d bytes)",
                        log_label,
                        int(elapsed),
                        remaining,
                        stdout_size,
                        stderr_size,
                    )
                    last_heartbeat = now

                time.sleep(0.1)
        except KeyboardInterrupt:
            _terminate_process(process)
            raise


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _check_output(path: Path, offset: int, label: str, stream: str) -> int:
    """Read new bytes from *path* since *offset*, log notable lines."""
    try:
        size = path.stat().st_size
    except OSError:
        return offset
    if size <= offset:
        return offset
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            new_text = fh.read()
    except OSError:
        return offset
    for raw_line in new_text.splitlines():
        stripped = raw_line.strip()
        if stripped and _NOTABLE_RE.search(stripped):
            logger.warning("[%s] agent %s: %s", label, stream, stripped)
    return size


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
