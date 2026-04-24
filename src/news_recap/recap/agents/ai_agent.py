"""Execute an LLM agent as a CLI subprocess or via direct API transport.

The function receives a pre-materialized workdir path, resolves agent routing,
and delegates execution to ``_run_agent_cli`` (CLI backend) or
``run_api_agent`` (API backend).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from news_recap.recap.agents.api_agent import run_api_agent
from news_recap.recap.agents.routing import resolve_routing_for_enqueue
from news_recap.recap.agents.subprocess import (
    SubprocessError,
    build_run_args,
    run_subprocess,
)
from news_recap.recap.contracts import (
    TaskManifest,
    read_manifest,
    read_task_input,
)
from news_recap.recap.exceptions import RecapPipelineError
from news_recap.recap.storage.pipeline_io import read_pipeline_input

if TYPE_CHECKING:
    from news_recap.recap.agents.concurrency import ConcurrencyController
    from news_recap.recap.agents.transport import LLMTransport

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 600
_TAIL_LINES = 30


def run_ai_agent(  # noqa: PLR0913
    pipeline_dir: str,
    step_name: str,
    task_id: str,
    stop_event: threading.Event | None = None,
    *,
    transport: LLMTransport | None = None,
    concurrency_controller: ConcurrencyController | None = None,
) -> str:
    """Execute an LLM agent, return *task_id* on success.

    Dispatches to the API backend (``run_api_agent``) when routing resolves
    ``execution_backend == "api"``, otherwise runs a CLI subprocess.
    """

    manifest_path = Path(pipeline_dir) / task_id / "meta" / "task_manifest.json"
    manifest = read_manifest(manifest_path)

    inp = read_pipeline_input(pipeline_dir)
    routing = resolve_routing_for_enqueue(
        defaults=inp.routing_defaults,
        task_type=step_name,
        agent_override=inp.agent_override,
        model_override=None,
    )
    timeout = inp.routing_defaults.task_type_timeout_map.get(step_name, _DEFAULT_TIMEOUT)

    logger.info(
        "[dim][cyan]%s:[/cyan] backend=%s agent=%s model=%s timeout=%ds[/dim]",
        step_name,
        routing.execution_backend,
        routing.agent,
        routing.model,
        timeout,
    )

    if routing.execution_backend == "api":
        if transport is None or concurrency_controller is None:
            raise RecapPipelineError(
                step_name,
                "transport and concurrency_controller are required for execution_backend=api "
                "(programming error: they were not passed to run_ai_agent)",
            )
        return run_api_agent(
            pipeline_dir=pipeline_dir,
            step_name=step_name,
            task_id=task_id,
            model=routing.model,
            transport=transport,
            concurrency_controller=concurrency_controller,
            timeout=timeout,
            max_backoff=concurrency_controller.max_backoff,
            jitter=concurrency_controller.jitter,
            stop_event=stop_event,
        )

    step_start = time.monotonic()
    result = _run_agent_cli(
        manifest=manifest,
        timeout_seconds=timeout,
        command_template=routing.command_template,
        model=routing.model,
        extra_env=routing.extra_env,
        api_key_vars=inp.routing_defaults.agent_api_key_vars.get(routing.agent, []),
        use_api_key=inp.use_api_key,
        log_label=step_name,
        stop_event=stop_event,
    )
    elapsed = time.monotonic() - step_start
    tokens = _parse_tokens_used(result.stderr_path)

    m, s = divmod(int(elapsed), 60)
    t = f"{m}m {s}s" if m else f"{elapsed:.1f}s"
    tokens_str = f" tokens={tokens:,}" if tokens else ""
    logger.info(
        "[green]✓[/green] [cyan]%s:[/cyan] Finished in %s%s",
        step_name,
        t,
        tokens_str,
    )

    _save_usage(Path(pipeline_dir) / task_id, elapsed=elapsed, tokens=tokens)

    if result.exit_code == 0:
        return task_id

    _log_agent_output(logger, step_name, result)
    summary = _summarise_output(result)
    if result.timed_out:
        detail = f" ({summary})" if summary else ""
        error = f"{routing.agent}: agent timed out{detail}"
    elif summary:
        error = f"{routing.agent}: {summary}"
    else:
        error = f"{routing.agent}: agent exit code {result.exit_code}"
    raise RecapPipelineError(step_name, error)


def _read_stderr_safe(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace").strip()
    except OSError:
        return ""


_KNOWN_ERRORS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"credit balance.{0,20}(too low|insufficient)|insufficient.{0,20}(funds|credits)",
            re.IGNORECASE,
        ),
        "Credit balance too low — add credits to continue",
    ),
    (
        re.compile(r"RetryableQuotaError:.*exhausted your capacity", re.IGNORECASE),
        "Gemini API quota exhausted (rate limit) — reduce parallelism or wait",
    ),
    (
        re.compile(r"OverloadedError|overloaded_error", re.IGNORECASE),
        "Claude API overloaded — reduce parallelism or retry later",
    ),
    (
        re.compile(r"rate.?limit|too many requests|429", re.IGNORECASE),
        "API rate limit hit — reduce parallelism or wait",
    ),
]


def _summarise_stderr(text: str) -> str | None:
    """Return a one-line summary if *text* matches a known error pattern."""
    for pattern, summary in _KNOWN_ERRORS:
        if pattern.search(text):
            return summary
    return None


def _summarise_output(result) -> str | None:
    """Check both stderr and stdout for known error patterns."""
    for path in (result.stderr_path, result.stdout_path):
        text = _read_stderr_safe(path)
        if text:
            summary = _summarise_stderr(text)
            if summary:
                return summary
    return None


def _log_agent_output(logger, step_name: str, result) -> None:
    """Read the tail of agent stderr/stdout and log it for quick diagnosis."""
    for label, path in [("stderr", result.stderr_path), ("stdout", result.stdout_path)]:
        try:
            text = path.read_text("utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        if label == "stderr":
            summary = _summarise_stderr(text)
            if summary:
                logger.error("[cyan]%s:[/cyan] agent %s: %s", step_name, label, summary)
                continue
        lines = text.splitlines()
        tail = lines[-_TAIL_LINES:]
        truncated = f"(last {_TAIL_LINES}/{len(lines)} lines)\n" if len(lines) > _TAIL_LINES else ""
        logger.error(
            "[cyan]%s:[/cyan] agent %s:\n%s%s",
            step_name,
            label,
            truncated,
            "\n".join(tail),
        )


_TOKENS_RE = re.compile(r"tokens\s+used\s*\n\s*([\d,]+)", re.IGNORECASE)


def _parse_tokens_used(stderr_path: Path) -> int | None:
    """Extract token count from agent stderr (codex format: ``tokens used\\n12,033``)."""
    try:
        text = stderr_path.read_text("utf-8", errors="replace")
    except OSError:
        return None
    m = _TOKENS_RE.search(text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


_USAGE_FILENAME = "meta/usage.json"


def _save_usage(task_dir: Path, *, elapsed: float, tokens: int | None) -> None:
    """Persist CLI agent usage metrics for later aggregation."""
    usage = {
        "elapsed_seconds": round(elapsed, 1),
        "tokens_used": tokens,
        "total_tokens": tokens,
        "backend": "cli",
    }
    path = task_dir / _USAGE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage), "utf-8")


def read_agent_usage(task_dir: Path) -> tuple[float, int]:
    """Read usage from a task workdir. Returns ``(elapsed, total_tokens)``.

    Compatible with both CLI usage.json (``tokens_used``) and API usage.json
    (``total_tokens``).
    """
    path = task_dir / _USAGE_FILENAME
    try:
        data = json.loads(path.read_text("utf-8"))
        elapsed = float(data.get("elapsed_seconds", 0))
        tokens = int(data.get("total_tokens") or data.get("tokens_used") or 0)
        return elapsed, tokens
    except (OSError, json.JSONDecodeError, ValueError):
        return 0.0, 0


# ---------------------------------------------------------------------------
# CLI agent subprocess
# ---------------------------------------------------------------------------


def _run_agent_cli(  # noqa: PLR0913
    *,
    manifest: TaskManifest,
    timeout_seconds: int,
    command_template: str,
    model: str,
    extra_env: dict[str, str] | None = None,
    api_key_vars: list[str] | None = None,
    use_api_key: bool = False,
    log_label: str = "",
    stop_event: threading.Event | None = None,
):
    """Render command and run the agent process in an isolated temp dir."""
    task_input = read_task_input(manifest.task_input_path)
    stdout_path = manifest.output_stdout_path
    stderr_path = manifest.output_stderr_path
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_file = Path(manifest.workdir) / "input" / "task_prompt.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(task_input.prompt, "utf-8")

    run_args, command_head = build_run_args(
        command_template,
        model=model,
        prompt_file=Path("input") / "task_prompt.txt",
    )

    if command_head == "codex":
        run_args = _inject_skip_git_flag(run_args)

    cmd_line = run_args if isinstance(run_args, str) else shlex.join(run_args)
    meta_dir = Path(manifest.workdir) / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "agent_command.txt").write_text(cmd_line, "utf-8")

    env = os.environ.copy()
    env["NEWS_RECAP_REPAIR_MODE"] = "0"
    env["NEWS_RECAP_LLM_AGENT"] = ""
    env["NEWS_RECAP_LLM_MODEL"] = model
    if not use_api_key and api_key_vars:
        for _key in api_key_vars:
            env.pop(_key, None)
    if extra_env:
        env.update(extra_env)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest = tmp / "input"
            dest.mkdir()
            (dest / "task_prompt.txt").write_text(task_input.prompt, "utf-8")

            return run_subprocess(
                run_args=run_args,
                env=env,
                cwd=tmp,
                timeout_seconds=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                log_label=log_label,
                stop_event=stop_event,
            )
    except FileNotFoundError as error:
        raise SubprocessError(
            f"Agent command not found: {command_head}",
            transient=False,
        ) from error
    except OSError as error:
        raise SubprocessError(
            f"Agent failed to start: {error}",
            transient=True,
        ) from error


def _inject_skip_git_flag(run_args: str | list[str]) -> str | list[str]:
    """Insert ``--skip-git-repo-check`` after ``codex exec``."""
    flag = "--skip-git-repo-check"
    if isinstance(run_args, list):
        if flag not in run_args:
            try:
                idx = run_args.index("exec") + 1
            except ValueError:
                idx = 1
            run_args = [*run_args[:idx], flag, *run_args[idx:]]
        return run_args
    if flag not in run_args:
        run_args = run_args.replace("codex exec", f"codex exec {flag}", 1)
    return run_args
