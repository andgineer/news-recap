"""Prefect @task that executes an LLM agent as a CLI subprocess.

The task receives a pre-materialized workdir path, resolves agent routing,
runs the agent via ``CliAgentBackend``, and returns the task_id on success.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import os
import time
from pathlib import Path

from prefect import task
from prefect.cache_policies import INPUTS
from prefect.logging import get_run_logger

from news_recap.recap.backend.base import BackendRunRequest
from news_recap.recap.backend.cli_backend import CliAgentBackend
from news_recap.recap.pipeline_io import read_pipeline_input
from news_recap.recap.routing import resolve_routing_for_enqueue
from news_recap.recap.runner import RecapPipelineError

_DEFAULT_TIMEOUT = 600
STEP_RETRIES = int(os.getenv("NEWS_RECAP_STEP_RETRIES", "1"))
STEP_RETRY_DELAY = 30
_GRACEFUL_SHUTDOWN = 30


@task(
    cache_policy=INPUTS,
    persist_result=True,
    retries=STEP_RETRIES,
    retry_delay_seconds=STEP_RETRY_DELAY,
)
def run_agent_step(
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
    request = BackendRunRequest(
        manifest_path=manifest_path,
        timeout_seconds=timeout,
        agent=routing.agent,
        profile=routing.profile,
        model=routing.model,
        command_template=routing.command_template,
        shutdown_requested=None,
        graceful_shutdown_seconds=_GRACEFUL_SHUTDOWN,
    )

    step_start = time.monotonic()
    result = CliAgentBackend().run(request)
    elapsed = time.monotonic() - step_start

    m, s = divmod(int(elapsed), 60)
    t = f"{m}m {s}s" if m else f"{elapsed:.1f}s"
    pf_logger.info("[%s] Finished in %s (exit=%s)", step_name, t, result.exit_code)

    if result.timed_out:
        raise RecapPipelineError(step_name, "agent timed out")
    if result.exit_code != 0:
        raise RecapPipelineError(step_name, f"agent exit code {result.exit_code}")

    return task_id
