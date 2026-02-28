"""Execute an LLM agent as a CLI subprocess.

The function receives a pre-materialized workdir path, resolves agent routing,
and delegates execution to ``task_subprocess``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import tempfile
import time
from pathlib import Path

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
from news_recap.recap.storage.pipeline_io import read_pipeline_input
from news_recap.recap.tasks.base import RecapPipelineError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 600
_TAIL_LINES = 30


def run_ai_agent(
    pipeline_dir: str,
    step_name: str,
    task_id: str,
) -> str:
    """Execute an LLM agent, return *task_id* on success."""

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
        "[%s] agent=%s model=%s timeout=%ds",
        step_name,
        routing.agent,
        routing.model,
        timeout,
    )

    step_start = time.monotonic()
    result = _run_agent_cli(
        manifest=manifest,
        timeout_seconds=timeout,
        command_template=routing.command_template,
        model=routing.model,
        log_label=step_name,
    )
    elapsed = time.monotonic() - step_start
    tokens = _parse_tokens_used(result.stderr_path)

    m, s = divmod(int(elapsed), 60)
    t = f"{m}m {s}s" if m else f"{elapsed:.1f}s"
    tokens_str = f" tokens={tokens:,}" if tokens else ""
    logger.info("[%s] Finished in %s (exit=%s)%s", step_name, t, result.exit_code, tokens_str)

    _save_usage(Path(pipeline_dir) / task_id, elapsed=elapsed, tokens=tokens)

    if result.exit_code == 0:
        return task_id

    _log_agent_output(logger, step_name, result)
    if result.timed_out:
        error = f"{routing.agent}: agent timed out"
    else:
        stderr_text = _read_stderr_safe(result.stderr_path)
        summary = _summarise_stderr(stderr_text) if stderr_text else None
        error = f"{routing.agent}: {summary}" if summary else f"agent exit code {result.exit_code}"
    raise RecapPipelineError(step_name, error)


def _read_stderr_safe(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace").strip()
    except OSError:
        return ""


_KNOWN_ERRORS: list[tuple[re.Pattern[str], str]] = [
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
                logger.error("[%s] agent %s: %s", step_name, label, summary)
                continue
        lines = text.splitlines()
        tail = lines[-_TAIL_LINES:]
        truncated = f"(last {_TAIL_LINES}/{len(lines)} lines)\n" if len(lines) > _TAIL_LINES else ""
        logger.error("[%s] agent %s:\n%s%s", step_name, label, truncated, "\n".join(tail))


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
    """Persist agent usage metrics for later aggregation."""
    usage = {"elapsed_seconds": round(elapsed, 1), "tokens_used": tokens}
    path = task_dir / _USAGE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage), "utf-8")


def read_agent_usage(task_dir: Path) -> tuple[float, int]:
    """Read usage from a task workdir. Returns ``(elapsed, tokens)``."""
    path = task_dir / _USAGE_FILENAME
    try:
        data = json.loads(path.read_text("utf-8"))
        return float(data.get("elapsed_seconds", 0)), int(data.get("tokens_used") or 0)
    except (OSError, json.JSONDecodeError, ValueError):
        return 0.0, 0


# ---------------------------------------------------------------------------
# CLI agent subprocess
# ---------------------------------------------------------------------------


def _run_agent_cli(
    *,
    manifest: TaskManifest,
    timeout_seconds: int,
    command_template: str,
    model: str,
    log_label: str = "",
):
    """Render command and run the agent process in an isolated temp dir."""
    task_input = read_task_input(Path(manifest.task_input_path))
    stdout_path = Path(manifest.output_stdout_path)
    stderr_path = Path(manifest.output_stderr_path)
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
