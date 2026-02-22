"""Prefect-based recap pipeline flow.

All pipeline data flows through files in the pipeline directory.
The ``@flow`` receives ``pipeline_dir`` (a string path).  Each ``@task``
receives ``pipeline_dir`` + step-specific scalars.  No module-level
globals carry business state.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from prefect import flow, task
from prefect.cache_policies import INPUTS
from prefect.logging import get_run_logger

from news_recap.agent_runtime import read_task_output
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
    build_classify_batch_prompt,
    build_event_payloads,
    events_to_resource_files,
    merge_enriched_into_index,
    parse_classify_batch_stdout,
    parse_enrich_result,
    parse_group_result,
    select_significant_events,
    split_into_classify_batches,
    to_article_index,
)
from news_recap.recap.schemas import SCHEMAS_BY_TASK_TYPE

logger = logging.getLogger(__name__)

_STEP_TIMEOUT = 600
_STEP_RETRIES = int(os.getenv("NEWS_RECAP_STEP_RETRIES", "1"))
_STEP_RETRY_DELAY = 30
_GRACEFUL_SHUTDOWN = 30
_CLASSIFY_MIN_BATCH_SUCCESS_RATE = 0.8


# ---------------------------------------------------------------------------
# Pipeline input contract — read from pipeline_dir/pipeline_input.json
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _PipelineInput:
    articles: list[SourceCorpusEntry]
    preferences: UserPreferences
    routing_defaults: RoutingDefaults
    agent_override: str | None


def _read_pipeline_input(pipeline_dir: str) -> _PipelineInput:
    path = Path(pipeline_dir) / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    return _PipelineInput(
        articles=[SourceCorpusEntry.from_dict(a) for a in raw["articles"]],
        preferences=UserPreferences.from_dict(raw["preferences"]),
        routing_defaults=RoutingDefaults.from_dict(raw["routing_defaults"]),
        agent_override=raw.get("agent_override"),
    )


# ---------------------------------------------------------------------------
# Workdir materialization helper (called from flow body, not from tasks)
# ---------------------------------------------------------------------------


def _make_task_id(step_name: str, batch: int | None = None) -> str:
    """Human-readable dir name: ``classify``, ``classify-1``, ``classify-2``."""
    short = step_name.removeprefix("recap_")
    if batch is not None:
        return f"{short}-{batch}"
    return short


def _materialize_step(  # noqa: PLR0913
    workdir_mgr: TaskWorkdirManager,
    inp: _PipelineInput,
    *,
    step_name: str,
    batch: int | None = None,
    article_entries: list[ArticleIndexEntry] | None = None,
    prompt: str | None = None,
    extra_input_files: dict[str, bytes | str] | None = None,
) -> str:
    """Create a task workdir with all input files.  Returns task_id."""
    task_id = _make_task_id(step_name, batch)
    entries = article_entries or []

    routing = resolve_routing_for_enqueue(
        defaults=inp.routing_defaults,
        task_type=step_name,
        agent_override=inp.agent_override,
        profile_override=None,
        model_override=None,
    )

    schema_hint: str | None = None
    if prompt is None:
        prompt_template = PROMPTS_BY_TASK_TYPE[step_name]
        prompt = prompt_template.format(
            preferences=inp.preferences.format_for_prompt(),
            max_headline_chars=inp.preferences.max_headline_chars,
        )
        schema_hint = SCHEMAS_BY_TASK_TYPE.get(step_name)

    workdir_mgr.materialize(
        task_id=task_id,
        task_type=step_name,
        task_input=TaskInputContract(
            task_type=step_name,
            prompt=prompt,
            metadata={"routing": routing.to_metadata()},
        ),
        articles_index=entries,
        extra_input_files=extra_input_files,
        output_schema_hint=schema_hint,
    )
    return task_id


# ---------------------------------------------------------------------------
# Resource loading (plain function, not a Prefect task)
# ---------------------------------------------------------------------------


def _load_resources(entries: list[ArticleIndexEntry]) -> dict[str, bytes | str]:
    if not entries:
        return {}
    resources: dict[str, bytes | str] = {}
    with ResourceLoader() as loader:
        for entry in entries:
            if not entry.url:
                continue
            loaded = loader.load(entry.url)
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
            else:
                logger.warning("Failed to load %s: %s", entry.source_id, loaded.error)
    return resources


# ---------------------------------------------------------------------------
# Prefect @task — runs agent in a pre-materialized workdir
# ---------------------------------------------------------------------------


@task(
    cache_policy=INPUTS,
    persist_result=True,
    retries=_STEP_RETRIES,
    retry_delay_seconds=_STEP_RETRY_DELAY,
)
def run_agent_step(
    pipeline_dir: str,
    step_name: str,
    task_id: str,
    timeout_seconds: int = _STEP_TIMEOUT,
) -> str:
    """Run an LLM agent whose workdir was already materialized by the flow."""
    pf_logger = get_run_logger()

    inp = _read_pipeline_input(pipeline_dir)
    routing = resolve_routing_for_enqueue(
        defaults=inp.routing_defaults,
        task_type=step_name,
        agent_override=inp.agent_override,
        profile_override=None,
        model_override=None,
    )
    pf_logger.info("[%s] agent=%s model=%s", step_name, routing.agent, routing.model)

    manifest_path = Path(pipeline_dir) / task_id / "meta" / "task_manifest.json"
    request = BackendRunRequest(
        manifest_path=manifest_path,
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

    pf_logger.info("[%s] Finished in %.1fs (exit=%s)", step_name, elapsed, result.exit_code)

    if result.timed_out:
        raise RecapPipelineError(step_name, "agent timed out")
    if result.exit_code != 0:
        raise RecapPipelineError(step_name, f"agent exit code {result.exit_code}")

    return task_id


# ---------------------------------------------------------------------------
# Pipeline phases (plain functions called from the @flow body)
# ---------------------------------------------------------------------------


def _run_classify_and_enrich(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: _PipelineInput,
    article_map: dict[str, ArticleIndexEntry],
    result: PipelineRunResult,
    *,
    classify_only: bool = False,
) -> tuple[list[ArticleIndexEntry], dict[str, dict[str, str]]]:
    pf_logger = get_run_logger()
    batches = split_into_classify_batches(inp.articles, inp.preferences)
    debug_max = int(os.getenv("NEWS_RECAP_CLASSIFY_MAX_BATCHES", "0")) or None
    if debug_max:
        batches = batches[:debug_max]
    n_batches = len(batches)
    pf_logger.info("[classify] %d articles -> %d batch(es)", len(inp.articles), n_batches)

    futures = []
    for i, batch in enumerate(batches):
        prompt = build_classify_batch_prompt(batch, inp.preferences)
        task_id = _materialize_step(
            workdir_mgr,
            inp,
            step_name="recap_classify",
            batch=i + 1,
            prompt=prompt,
        )
        pf_logger.info("[classify] Batch %d/%d — %d headlines", i + 1, n_batches, len(batch))
        future = run_agent_step.with_options(task_run_name=task_id).submit(
            pipeline_dir=str(pdir),
            step_name="recap_classify",
            task_id=task_id,
        )
        futures.append((i, batch, future))

    all_kept: list[str] = []
    all_enrich: list[str] = []
    failed_batches = 0
    for i, batch, future in futures:
        try:
            tid = future.result()
            verdicts_path = pdir / tid / "output" / "agent_stdout.log"
            kept, enrich = parse_classify_batch_stdout(verdicts_path, batch)
            all_kept.extend(kept)
            all_enrich.extend(enrich)
            result.steps.append(
                PipelineStepResult(f"classify batch {i + 1}", tid, "completed"),
            )
        except Exception:  # noqa: BLE001
            pf_logger.exception("classify batch %d failed", i + 1)
            failed_batches += 1
            result.steps.append(PipelineStepResult(f"classify batch {i + 1}", None, "failed"))

    if failed_batches > 0:
        success_rate = (n_batches - failed_batches) / n_batches
        if success_rate < _CLASSIFY_MIN_BATCH_SUCCESS_RATE:
            raise RecapPipelineError(
                "recap_classify",
                f"Too many batch failures: {failed_batches}/{n_batches} failed",
            )
        pf_logger.warning(
            "[classify] %d/%d batches failed — partial results",
            failed_batches,
            n_batches,
        )

    kept_entries = [article_map[sid] for sid in all_kept if sid in article_map]
    pf_logger.info(
        "Classify: %d kept, %d discarded, %d need enrichment",
        len(all_kept),
        len(inp.articles) - len(all_kept),
        len(all_enrich),
    )

    if classify_only:
        pf_logger.info("Classify-only mode: stopping before enrich.")
        return kept_entries, {}

    resource_entries = [article_map[sid] for sid in all_enrich if sid in article_map]
    loaded = _load_resources(resource_entries)
    result.steps.append(PipelineStepResult("resource_load", None, "completed"))

    tid = _materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_enrich",
        article_entries=kept_entries,
        extra_input_files=loaded,
    )
    tid = run_agent_step.with_options(task_run_name=tid)(
        pipeline_dir=str(pdir),
        step_name="recap_enrich",
        task_id=tid,
    )
    result.steps.append(PipelineStepResult("recap_enrich", tid, "completed"))
    enriched = parse_enrich_result(read_task_output(pdir, tid))
    pf_logger.info("Enrich: %d articles enriched", len(enriched))

    return kept_entries, enriched


def _run_group_and_deep_enrich(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: _PipelineInput,
    kept_entries: list[ArticleIndexEntry],
    enriched_articles: dict[str, dict[str, str]],
    article_map: dict[str, ArticleIndexEntry],
    result: PipelineRunResult,
) -> list[dict[str, Any]]:
    pf_logger = get_run_logger()
    enriched_entries = merge_enriched_into_index(kept_entries, enriched_articles)

    tid = _materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_group",
        article_entries=enriched_entries,
    )
    tid = run_agent_step.with_options(task_run_name=tid)(
        pipeline_dir=str(pdir),
        step_name="recap_group",
        task_id=tid,
    )
    result.steps.append(PipelineStepResult("recap_group", tid, "completed"))
    events = parse_group_result(read_task_output(pdir, tid))
    pf_logger.info("Group: %d events identified", len(events))

    significant = select_significant_events(events)
    articles_for_full = articles_needing_full_text(significant, article_map)
    pf_logger.info(
        "Significant events: %d, articles needing full text: %d",
        len(significant),
        len(articles_for_full),
    )
    full_resources = _load_resources(articles_for_full)

    enrich_full_payload: dict[str, Any] = {"enriched": []}
    if full_resources:
        tid = _materialize_step(
            workdir_mgr,
            inp,
            step_name="recap_enrich_full",
            article_entries=articles_for_full,
            extra_input_files=full_resources,
        )
        tid = run_agent_step.with_options(task_run_name=tid)(
            pipeline_dir=str(pdir),
            step_name="recap_enrich_full",
            task_id=tid,
        )
        result.steps.append(PipelineStepResult("recap_enrich_full", tid, "completed"))
        enrich_full_payload = read_task_output(pdir, tid)
    enriched_full = parse_enrich_result(enrich_full_payload)

    return build_event_payloads(events, enriched_articles, enriched_full, article_map)


def _run_synthesize_and_compose(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: _PipelineInput,
    kept_entries: list[ArticleIndexEntry],
    event_payloads: list[dict[str, Any]],
    result: PipelineRunResult,
) -> dict[str, Any]:
    synth_resources = events_to_resource_files(event_payloads)

    tid = _materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_synthesize",
        article_entries=kept_entries,
        extra_input_files=synth_resources,
    )
    tid = run_agent_step.with_options(task_run_name=tid)(
        pipeline_dir=str(pdir),
        step_name="recap_synthesize",
        task_id=tid,
    )
    result.steps.append(PipelineStepResult("recap_synthesize", tid, "completed"))

    tid = _materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_compose",
        article_entries=kept_entries,
        extra_input_files=synth_resources,
    )
    tid = run_agent_step.with_options(task_run_name=tid)(
        pipeline_dir=str(pdir),
        step_name="recap_compose",
        task_id=tid,
    )
    result.steps.append(PipelineStepResult("recap_compose", tid, "completed"))
    return read_task_output(pdir, tid)


# ---------------------------------------------------------------------------
# Prefect @flow
# ---------------------------------------------------------------------------


def _flow_run_name(
    business_date: str = "",  # noqa: ARG001
    **_kwargs: Any,
) -> str:
    now = datetime.now(tz=UTC).strftime("%H:%M:%S")
    return f"recap {business_date} {now}"


@flow(name="recap_pipeline", flow_run_name=_flow_run_name)
def recap_flow(
    pipeline_dir: str,
    business_date: str,
    classify_only: bool = False,
) -> PipelineRunResult:
    """Prefect flow — only simple, serializable parameters."""
    pf_logger = get_run_logger()
    pdir = Path(pipeline_dir)
    inp = _read_pipeline_input(pipeline_dir)
    workdir_mgr = TaskWorkdirManager(pdir)

    pipeline_id = str(uuid4())
    bd = date.fromisoformat(business_date)
    result = PipelineRunResult(pipeline_id=pipeline_id, business_date=bd)
    n = len(inp.articles)
    pf_logger.info("Pipeline starting: %d articles, date=%s", n, business_date)

    try:
        article_entries = to_article_index(inp.articles)
        article_map = {e.source_id: e for e in article_entries}

        _classify_only = classify_only or bool(os.getenv("NEWS_RECAP_CLASSIFY_ONLY"))
        kept_entries, enriched_articles = _run_classify_and_enrich(
            pdir,
            workdir_mgr,
            inp,
            article_map,
            result,
            classify_only=_classify_only,
        )

        if _classify_only:
            result.status = "completed"
            pf_logger.info("Classify-only mode done: %d kept", len(kept_entries))
            return result

        event_payloads = _run_group_and_deep_enrich(
            pdir,
            workdir_mgr,
            inp,
            kept_entries,
            enriched_articles,
            article_map,
            result,
        )
        result.digest = _run_synthesize_and_compose(
            pdir,
            workdir_mgr,
            inp,
            kept_entries,
            event_payloads,
            result,
        )
        result.status = "completed"
        pf_logger.info("Pipeline completed")

    except RecapPipelineError as exc:
        result.steps.append(
            PipelineStepResult(exc.step, None, "failed", error=str(exc)),
        )
        result.status = "failed"
        result.error = str(exc)
        pf_logger.error("Pipeline failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.error = f"Unexpected error: {exc}"
        pf_logger.exception("Pipeline unexpected error")

    return result
