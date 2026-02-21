"""Shared Prefect tasks for running CLI LLM agents.

Neutral module imported by both ``recap/prefect_flow.py`` (recap pipeline)
and ``brain/flows.py`` (intelligence layer).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from prefect import task

from news_recap.brain.backend.base import BackendRunRequest
from news_recap.brain.backend.cli_backend import CliAgentBackend
from news_recap.brain.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.brain.routing import RoutingDefaults, resolve_routing_for_enqueue
from news_recap.brain.workdir import TaskWorkdirManager
from news_recap.recap.resource_loader import ResourceLoader

logger = logging.getLogger(__name__)

_STEP_RETRIES = 2
_STEP_RETRY_DELAY = 30
_GRACEFUL_SHUTDOWN = 30


def read_task_output(workdir_root: Path, task_id: str) -> dict[str, Any]:
    """Read agent_result.json from a completed task workdir."""
    path = workdir_root / task_id / "output" / "agent_result.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}


def task_results_dir(workdir_root: Path, task_id: str) -> Path:
    """Return the results subdirectory for a task."""
    return workdir_root / task_id / "output" / "results"


@dataclass(slots=True)
class AgentTaskResult:
    """Result of a generic agent task execution."""

    task_id: str
    output: dict[str, Any]
    agent: str
    model: str
    elapsed_seconds: float


@task(retries=_STEP_RETRIES, retry_delay_seconds=_STEP_RETRY_DELAY)
def run_agent_task(  # noqa: PLR0913
    *,
    task_type: str,
    prompt: str,
    workdir_mgr: TaskWorkdirManager,
    routing_defaults: RoutingDefaults,
    article_entries: list[ArticleIndexEntry],
    agent_override: str | None = None,
    profile_override: str | None = None,
    model_override: str | None = None,
    metadata: dict[str, object] | None = None,
    continuity_summary: dict[str, object] | None = None,
    retrieval_context: dict[str, object] | None = None,
    story_context: dict[str, object] | None = None,
    timeout_seconds: int = 600,
) -> AgentTaskResult:
    """Execute one LLM task via CLI agent subprocess and return parsed output.

    Generic version used by intelligence flows (highlights, story details,
    monitors, Q&A).  Materializes workdir, resolves routing, calls
    ``CliAgentBackend`` directly (no task-queue, no polling).
    """
    task_id = str(uuid4())
    routing = resolve_routing_for_enqueue(
        defaults=routing_defaults,
        task_type=task_type,
        agent_override=agent_override,
        profile_override=profile_override,
        model_override=model_override,
    )

    task_metadata: dict[str, object] = {"routing": routing.to_metadata()}
    if metadata:
        task_metadata.update(metadata)

    materialized = workdir_mgr.materialize(
        task_id=task_id,
        task_type=task_type,
        task_input=TaskInputContract(
            task_type=task_type,
            prompt=prompt,
            metadata=task_metadata,
        ),
        articles_index=article_entries,
        continuity_summary=continuity_summary,
        retrieval_context=retrieval_context,
        story_context=story_context,
    )

    request = BackendRunRequest(
        manifest_path=materialized.manifest_path,
        timeout_seconds=timeout_seconds,
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

    if result.timed_out:
        raise RuntimeError(f"Agent timed out after {elapsed:.1f}s for task_type={task_type}")
    if result.exit_code != 0:
        raise RuntimeError(
            f"Agent exit code {result.exit_code} after {elapsed:.1f}s for task_type={task_type}",
        )

    output = read_task_output(workdir_mgr.root_dir, task_id)
    logger.info(
        "Agent task completed: task_type=%s task_id=%s elapsed=%.1fs",
        task_type,
        task_id,
        elapsed,
    )

    return AgentTaskResult(
        task_id=task_id,
        output=output,
        agent=routing.agent,
        model=routing.model or "",
        elapsed_seconds=elapsed,
    )


@task
def load_resources_step(
    *,
    entries: list[ArticleIndexEntry],
    resource_loader: ResourceLoader | None,
) -> dict[str, bytes | str]:
    """Load full article texts from URLs via ``ResourceLoader``."""
    if not entries or resource_loader is None:
        return {}

    resources: dict[str, bytes | str] = {}
    ok = fail = 0
    for entry in entries:
        if not entry.url:
            continue
        loaded = resource_loader.load(entry.url)
        if loaded.is_success and loaded.text:
            safe_id = entry.source_id.replace(":", "_").replace("/", "_")
            resources[f"{safe_id}.json"] = json.dumps(
                {
                    "article_id": entry.source_id,
                    "title": entry.title,
                    "url": entry.url,
                    "source": entry.source,
                    "text": loaded.text,
                    "content_type": loaded.content_type,
                },
                ensure_ascii=False,
                indent=2,
            )
            ok += 1
        else:
            fail += 1
            logger.warning("Failed to load %s (%s): %s", entry.source_id, entry.url, loaded.error)

    logger.info("Resource loading: ok=%d fail=%d", ok, fail)
    return resources
