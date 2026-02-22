"""Prefect @flow for the recap pipeline and its phase functions.

Orchestrates classify -> enrich -> group -> deep-enrich -> synthesize -> compose.
Each phase materializes workdirs on disk and delegates execution to
``run_agent_step`` (the Prefect @task in ``agent_task.py``).

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from prefect import flow
from prefect.logging import get_run_logger

from news_recap.recap.agent_task import run_agent_step
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.pipeline_io import (
    PipelineInput,
    load_resources,
    materialize_step,
    read_pipeline_input,
    read_task_output,
)
from news_recap.recap.runner import (
    PipelineRunResult,
    PipelineStepResult,
    RecapPipelineError,
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
from news_recap.recap.workdir import TaskWorkdirManager

_CLASSIFY_MIN_BATCH_SUCCESS_RATE = 0.8


def _run_classify_and_enrich(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    article_map: dict[str, ArticleIndexEntry],
    result: PipelineRunResult,
    *,
    classify_only: bool = False,
) -> tuple[list[ArticleIndexEntry], dict[str, dict[str, str]]]:
    """Batch-classify articles and optionally enrich unclear ones."""
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
        task_id = materialize_step(
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
    loaded = load_resources(resource_entries)
    result.steps.append(PipelineStepResult("resource_load", None, "completed"))

    tid = materialize_step(
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
    inp: PipelineInput,
    kept_entries: list[ArticleIndexEntry],
    enriched_articles: dict[str, dict[str, str]],
    article_map: dict[str, ArticleIndexEntry],
    result: PipelineRunResult,
) -> list[dict[str, Any]]:
    """Group articles into events, then deep-enrich significant ones."""
    pf_logger = get_run_logger()
    enriched_entries = merge_enriched_into_index(kept_entries, enriched_articles)

    tid = materialize_step(
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
    full_resources = load_resources(articles_for_full)

    enrich_full_payload: dict[str, Any] = {"enriched": []}
    if full_resources:
        tid = materialize_step(
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
    inp: PipelineInput,
    kept_entries: list[ArticleIndexEntry],
    event_payloads: list[dict[str, Any]],
    result: PipelineRunResult,
) -> dict[str, Any]:
    """Synthesize event narratives, then compose the final digest."""
    synth_resources = events_to_resource_files(event_payloads)

    tid = materialize_step(
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

    tid = materialize_step(
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


def _flow_run_name(
    business_date: str = "",  # noqa: ARG001
    **_kwargs: Any,
) -> str:
    """Generate a human-readable flow run name with timestamp."""
    now = datetime.now(tz=UTC).strftime("%H:%M:%S")
    return f"recap {business_date} {now}"


@flow(name="recap_pipeline", flow_run_name=_flow_run_name)
def recap_flow(
    pipeline_dir: str,
    business_date: str,
    classify_only: bool = False,
) -> PipelineRunResult:
    """Top-level Prefect flow for the daily recap pipeline."""
    pf_logger = get_run_logger()
    pdir = Path(pipeline_dir)
    inp = read_pipeline_input(pipeline_dir)
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
