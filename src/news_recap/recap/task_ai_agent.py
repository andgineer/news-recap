"""Prefect @task that executes an LLM agent as a CLI subprocess.

The task receives a pre-materialized workdir path, resolves agent routing,
enriches the prompt with manifest context, and delegates execution to
``task_subprocess``.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import os
import shlex
import time
from pathlib import Path

from prefect import task
from prefect.cache_policies import INPUTS
from prefect.logging import get_run_logger

from news_recap.recap.contracts import (
    TaskManifest,
    read_manifest,
    read_task_input,
)
from news_recap.recap.pipeline_io import read_pipeline_input
from news_recap.recap.routing import resolve_routing_for_enqueue
from news_recap.recap.runner import RecapPipelineError
from news_recap.recap.task_subprocess import (
    SubprocessError,
    build_run_args,
    run_subprocess,
)

_DEFAULT_TIMEOUT = 600
STEP_RETRIES = int(os.getenv("NEWS_RECAP_STEP_RETRIES", "1"))
STEP_RETRY_DELAY = 30
_GRACEFUL_SHUTDOWN = 30


# ---------------------------------------------------------------------------
# Prefect task
# ---------------------------------------------------------------------------


@task(
    cache_policy=INPUTS,
    persist_result=True,
    retries=STEP_RETRIES,
    retry_delay_seconds=STEP_RETRY_DELAY,
)
def run_ai_agent(
    pipeline_dir: str,
    step_name: str,
    task_id: str,
) -> str:
    """Execute an LLM agent in a pre-materialized workdir and return task_id."""
    pf_logger = get_run_logger()

    inp = read_pipeline_input(pipeline_dir)
    routing = resolve_routing_for_enqueue(
        defaults=inp.routing_defaults,
        task_type=step_name,
        agent_override=inp.agent_override,
        profile_override=None,
        model_override=None,
    )
    timeout = inp.routing_defaults.task_type_timeout_map.get(step_name, _DEFAULT_TIMEOUT)
    pf_logger.info(
        "[%s] agent=%s model=%s timeout=%ds",
        step_name,
        routing.agent,
        routing.model,
        timeout,
    )

    manifest_path = Path(pipeline_dir) / task_id / "meta" / "task_manifest.json"

    step_start = time.monotonic()
    result = _run_agent_cli(
        manifest_path=manifest_path,
        timeout_seconds=timeout,
        command_template=routing.command_template,
        model=routing.model,
    )
    elapsed = time.monotonic() - step_start

    m, s = divmod(int(elapsed), 60)
    t = f"{m}m {s}s" if m else f"{elapsed:.1f}s"
    pf_logger.info("[%s] Finished in %s (exit=%s)", step_name, t, result.exit_code)

    if result.timed_out:
        raise RecapPipelineError(step_name, "agent timed out")
    if result.exit_code != 0:
        raise RecapPipelineError(step_name, f"agent exit code {result.exit_code}")

    return task_id


# ---------------------------------------------------------------------------
# CLI agent subprocess
# ---------------------------------------------------------------------------


def _run_agent_cli(
    *,
    manifest_path: Path,
    timeout_seconds: int,
    command_template: str,
    model: str,
):
    """Enrich prompt, render command, and run the agent process."""
    manifest = read_manifest(manifest_path)
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

    run_args, command_head = build_run_args(
        command_template,
        model=model,
        prompt_file=Path("input") / "task_prompt.txt",
    )

    cmd_line = run_args if isinstance(run_args, str) else shlex.join(run_args)
    meta_dir = Path(manifest.workdir) / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "agent_command.txt").write_text(cmd_line, "utf-8")

    env = os.environ.copy()
    env["NEWS_RECAP_REPAIR_MODE"] = "0"
    env["NEWS_RECAP_LLM_AGENT"] = ""
    env["NEWS_RECAP_LLM_MODEL"] = model
    env["NEWS_RECAP_LLM_MODEL_PROFILE"] = ""

    try:
        return run_subprocess(
            run_args=run_args,
            env=env,
            cwd=Path(manifest.workdir),
            timeout_seconds=timeout_seconds,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
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


# ---------------------------------------------------------------------------
# Prompt enrichment
# ---------------------------------------------------------------------------

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

    if manifest.task_type.startswith("recap_classify"):
        return base_prompt

    if manifest.output_schema_hint or manifest.input_resources_dir:
        return _build_v3_prompt(
            base_prompt=base_prompt,
            manifest=manifest,
            manifest_path=manifest_path,
        )

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


def _build_v3_prompt(
    *,
    base_prompt: str,
    manifest: TaskManifest,
    manifest_path: str,
) -> str:
    """Build enriched prompt for contract v3 tasks with custom I/O."""
    parts = [
        base_prompt,
        "",
        f"Your task manifest is at: {manifest_path}",
        "",
        "Steps:",
        "1. Read the manifest JSON — it contains paths to all input/output files.",
    ]

    step = 2
    if manifest.input_resources_dir:
        parts.append(
            f"{step}. Read input files from input_resources_dir: {manifest.input_resources_dir}\n"
            f"   Process all files in this directory.",
        )
        step += 1
    else:
        parts.append(
            f"{step}. Read articles_index_path from the manifest — each article has a source_id,\n"
            f"   title, url, and source. Use these as your source material.",
        )
        step += 1

    parts.append(f"{step}. Write the result to output_result_path from the manifest.")
    step += 1

    if manifest.output_schema_hint:
        parts.append(
            f"{step}. The output file must follow this JSON schema:\n{manifest.output_schema_hint}",
        )
        step += 1
    else:
        parts.append(
            f"{step}. The output file must follow this JSON schema exactly:\n"
            f"{_OUTPUT_SCHEMA_EXAMPLE}",
        )
        step += 1

    if manifest.output_results_dir:
        parts.append(
            f"{step}. If the task produces per-item results, write them as individual JSON files\n"
            f"   to output_results_dir: {manifest.output_results_dir}",
        )
        step += 1

    parts.append("")
    parts.append("Do not search the web. Write only the output files.")
    parts.append(
        "Read all input files listed above, analyse the data, and write the output.",
    )

    return "\n".join(parts)
