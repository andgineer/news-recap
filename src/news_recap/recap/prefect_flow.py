"""Prefect-based recap pipeline flow.

Replaces the legacy enqueue -> worker-thread -> poll loop with direct agent
subprocess execution wrapped in Prefect tasks.  Business-logic helpers
(article parsing, event building, etc.) are reused from ``runner.py``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from prefect import flow, task

from news_recap.agent_runtime import (
    load_resources_step,
    read_task_output,
    task_results_dir,
)
from news_recap.brain.backend.base import BackendRunRequest
from news_recap.brain.backend.cli_backend import CliAgentBackend
from news_recap.brain.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.brain.models import SourceCorpusEntry
from news_recap.brain.routing import RoutingDefaults, resolve_routing_for_enqueue
from news_recap.brain.workdir import TaskWorkdirManager
from news_recap.recap.prompts import PROMPTS_BY_TASK_TYPE
from news_recap.recap.resource_loader import ResourceLoader
from news_recap.recap.runner import (
    PipelineRunResult,
    PipelineStepResult,
    RecapPipelineError,
    UserPreferences,
    articles_needing_full_text,
    articles_to_individual_files,
    build_event_payloads,
    events_to_resource_files,
    merge_enriched_into_index,
    parse_classify_out_files,
    parse_enrich_result,
    parse_group_result,
    select_significant_events,
    to_article_index,
)
from news_recap.recap.schemas import SCHEMAS_BY_TASK_TYPE

logger = logging.getLogger(__name__)

_STEP_TIMEOUT = 600
_STEP_RETRIES = 2
_STEP_RETRY_DELAY = 30
_GRACEFUL_SHUTDOWN = 30


@task(retries=_STEP_RETRIES, retry_delay_seconds=_STEP_RETRY_DELAY)
def run_agent_step(  # noqa: PLR0913
    *,
    step_name: str,
    workdir_mgr: TaskWorkdirManager,
    routing_defaults: RoutingDefaults,
    article_entries: list[ArticleIndexEntry],
    preferences: UserPreferences,
    extra_input_files: dict[str, bytes | str] | None = None,
    agent_override: str | None = None,
    timeout_seconds: int = _STEP_TIMEOUT,
    emit: Callable[[str], None] = lambda _: None,
) -> str:
    """Execute one LLM pipeline step via agent subprocess.

    Materializes workdir, resolves routing, calls ``CliAgentBackend`` directly
    (no task-queue, no polling).  Returns the task_id used to locate outputs.
    """
    task_id = str(uuid4())
    n_res = len(extra_input_files) if extra_input_files else 0
    emit(f"[{step_name}] Starting — {len(article_entries)} articles, {n_res} resource files")

    prompt_template = PROMPTS_BY_TASK_TYPE[step_name]
    prompt = prompt_template.format(
        preferences=preferences.format_for_prompt(),
        max_headline_chars=preferences.max_headline_chars,
    )
    schema_hint = SCHEMAS_BY_TASK_TYPE.get(step_name)

    routing = resolve_routing_for_enqueue(
        defaults=routing_defaults,
        task_type=step_name,
        agent_override=agent_override,
        profile_override=None,
        model_override=None,
    )

    materialized = workdir_mgr.materialize(
        task_id=task_id,
        task_type=step_name,
        task_input=TaskInputContract(
            task_type=step_name,
            prompt=prompt,
            metadata={"routing": routing.to_metadata()},
        ),
        articles_index=article_entries,
        extra_input_files=extra_input_files,
        output_schema_hint=schema_hint,
    )

    if step_name == "recap_classify":
        input_dir = workdir_mgr.root_dir / task_id / "input"
        input_dir.joinpath("_discard.txt").write_text(preferences.not_interesting, "utf-8")
        input_dir.joinpath("_priority.txt").write_text(preferences.interesting, "utf-8")

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
        emit(f"[{step_name}] Timed out after {elapsed:.1f}s")
        raise RecapPipelineError(step_name, "agent timed out")
    if result.exit_code != 0:
        emit(f"[{step_name}] Failed (exit {result.exit_code}) after {elapsed:.1f}s")
        raise RecapPipelineError(step_name, f"agent exit code {result.exit_code}")

    emit(f"[{step_name}] Completed in {elapsed:.1f}s")
    return task_id


# ---------------------------------------------------------------------------
# Prefect flow
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _FlowContext:
    """Shared state threaded through pipeline steps."""

    workdir_root: Path
    workdir_mgr: TaskWorkdirManager
    routing_defaults: RoutingDefaults
    preferences: UserPreferences
    resource_loader: ResourceLoader | None
    agent_override: str | None
    emit: Callable[[str], None]

    def agent_step(
        self,
        step_name: str,
        article_entries: list[ArticleIndexEntry],
        extra_input_files: dict[str, bytes | str] | None = None,
    ) -> str:
        """Run an LLM step and return its task_id."""
        return run_agent_step(
            step_name=step_name,
            workdir_mgr=self.workdir_mgr,
            routing_defaults=self.routing_defaults,
            article_entries=article_entries,
            preferences=self.preferences,
            extra_input_files=extra_input_files,
            agent_override=self.agent_override,
            emit=self.emit,
        )

    def read_output(self, task_id: str) -> dict[str, Any]:
        return read_task_output(self.workdir_root, task_id)

    def results_dir(self, task_id: str) -> Path:
        return task_results_dir(self.workdir_root, task_id)


def _run_classify_and_enrich(
    ctx: _FlowContext,
    articles: list[SourceCorpusEntry],
    article_entries: list[ArticleIndexEntry],
    article_map: dict[str, ArticleIndexEntry],
    result: PipelineRunResult,
) -> tuple[list[ArticleIndexEntry], dict[str, dict[str, str]]]:
    """Steps 1-3: classify, resource_load, enrich."""
    per_article_files = articles_to_individual_files(articles)
    tid = ctx.agent_step("recap_classify", article_entries, per_article_files)
    result.steps.append(PipelineStepResult("recap_classify", tid, "completed"))

    kept_ids, enrich_ids = parse_classify_out_files(ctx.results_dir(tid), articles)
    kept_entries = [article_map[sid] for sid in kept_ids if sid in article_map]
    ctx.emit(
        f"Classify: {len(kept_ids)} kept, {len(articles) - len(kept_ids)} discarded, "
        f"{len(enrich_ids)} need enrichment",
    )

    resource_entries = [article_map[sid] for sid in enrich_ids if sid in article_map]
    loaded = load_resources_step(
        entries=resource_entries,
        resource_loader=ctx.resource_loader,
    )
    result.steps.append(PipelineStepResult("resource_load", None, "completed"))

    tid = ctx.agent_step("recap_enrich", kept_entries, loaded)
    result.steps.append(PipelineStepResult("recap_enrich", tid, "completed"))
    enriched = parse_enrich_result(ctx.read_output(tid))
    ctx.emit(f"Enrich: {len(enriched)} articles enriched")

    return kept_entries, enriched


def _run_group_and_deep_enrich(
    ctx: _FlowContext,
    kept_entries: list[ArticleIndexEntry],
    enriched_articles: dict[str, dict[str, str]],
    article_map: dict[str, ArticleIndexEntry],
    result: PipelineRunResult,
) -> list[dict[str, Any]]:
    """Steps 4-4c: group, resource_load_full, enrich_full, merge payloads."""
    enriched_entries = merge_enriched_into_index(kept_entries, enriched_articles)
    tid = ctx.agent_step("recap_group", enriched_entries)
    result.steps.append(PipelineStepResult("recap_group", tid, "completed"))
    events = parse_group_result(ctx.read_output(tid))
    ctx.emit(f"Group: {len(events)} events identified")

    significant = select_significant_events(events)
    articles_for_full = articles_needing_full_text(significant, article_map)
    ctx.emit(
        f"Significant events: {len(significant)}, "
        f"articles needing full text: {len(articles_for_full)}",
    )
    full_resources = load_resources_step(
        entries=articles_for_full,
        resource_loader=ctx.resource_loader,
    )

    enrich_full_payload: dict[str, Any] = {"enriched": []}
    if full_resources:
        tid = ctx.agent_step("recap_enrich_full", articles_for_full, full_resources)
        result.steps.append(PipelineStepResult("recap_enrich_full", tid, "completed"))
        enrich_full_payload = ctx.read_output(tid)
    enriched_full = parse_enrich_result(enrich_full_payload)

    return build_event_payloads(events, enriched_articles, enriched_full, article_map)


def _run_synthesize_and_compose(
    ctx: _FlowContext,
    kept_entries: list[ArticleIndexEntry],
    event_payloads: list[dict[str, Any]],
    result: PipelineRunResult,
) -> dict[str, Any]:
    """Steps 5-6: synthesize, compose.  Returns final digest."""
    synth_resources = events_to_resource_files(event_payloads)

    tid = ctx.agent_step("recap_synthesize", kept_entries, synth_resources)
    result.steps.append(PipelineStepResult("recap_synthesize", tid, "completed"))

    tid = ctx.agent_step("recap_compose", kept_entries, synth_resources)
    result.steps.append(PipelineStepResult("recap_compose", tid, "completed"))
    return ctx.read_output(tid)


@flow(name="recap_flow")
def recap_flow(  # noqa: PLR0913
    *,
    business_date: date,
    preferences: UserPreferences,
    articles: list[SourceCorpusEntry],
    workdir_root: Path,
    routing_defaults: RoutingDefaults,
    resource_loader: ResourceLoader | None = None,
    agent_override: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> PipelineRunResult:
    """Execute the full recap pipeline as a Prefect flow.

    Each LLM step runs as a Prefect task with automatic retry.
    Agent subprocesses are called directly via ``CliAgentBackend`` —
    no task-queue, no worker threads, no polling.
    """
    emit = on_progress or (lambda _: None)
    pipeline_id = str(uuid4())
    result = PipelineRunResult(pipeline_id=pipeline_id, business_date=business_date)
    pipeline_start = time.monotonic()
    emit(f"Pipeline {pipeline_id[:12]} started: {len(articles)} articles, date={business_date}")

    ctx = _FlowContext(
        workdir_root=workdir_root,
        workdir_mgr=TaskWorkdirManager(workdir_root),
        routing_defaults=routing_defaults,
        preferences=preferences,
        resource_loader=resource_loader,
        agent_override=agent_override,
        emit=emit,
    )

    try:
        article_entries = to_article_index(articles)
        article_map = {e.source_id: e for e in article_entries}

        kept_entries, enriched_articles = _run_classify_and_enrich(
            ctx,
            articles,
            article_entries,
            article_map,
            result,
        )
        event_payloads = _run_group_and_deep_enrich(
            ctx,
            kept_entries,
            enriched_articles,
            article_map,
            result,
        )
        result.digest = _run_synthesize_and_compose(ctx, kept_entries, event_payloads, result)
        result.status = "completed"
        elapsed = time.monotonic() - pipeline_start
        emit(f"Pipeline {pipeline_id[:12]} completed in {elapsed:.1f}s")

    except RecapPipelineError as exc:
        result.steps.append(
            PipelineStepResult(step_name=exc.step, task_id=None, status="failed", error=str(exc)),
        )
        result.status = "failed"
        result.error = str(exc)
        logger.error("Pipeline %s failed: %s", pipeline_id, exc)
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.error = f"Unexpected error: {exc}"
        logger.exception("Pipeline %s unexpected error", pipeline_id)

    return result
