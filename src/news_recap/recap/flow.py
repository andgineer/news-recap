"""Prefect @flow for the DB-centric recap pipeline.

Each step queries the DB for work, materializes a task workdir,
checks for cached agent output (input_hash), runs the agent only
if needed, then commits results to DB.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from prefect import flow
from prefect.logging import get_run_logger

from news_recap.ingestion.repository import SQLiteRepository
from news_recap.recap.agent_task import run_agent_step
from news_recap.recap.pipeline_io import (
    DebugStopError,
    PipelineInput,
    check_cached_output,
    commit_with_retry,
    compute_input_hash,
    load_resources,
    materialize_step,
    read_pipeline_input,
    read_task_output,
    save_input_hash,
)
from news_recap.recap.runner import (
    MIN_ARTICLES_FOR_SIGNIFICANT_EVENT,
    PipelineRunResult,
    PipelineStepResult,
    RecapPipelineError,
    build_classify_batch_prompt,
    parse_classify_batch_stdout,
    parse_enrich_result,
    parse_group_result,
    split_into_classify_batches,
    to_article_index,
)
from news_recap.recap.workdir import TaskWorkdirManager

_CLASSIFY_MIN_BATCH_SUCCESS_RATE = 0.8


def _source_id_to_article_id(source_id: str) -> str:
    return source_id.removeprefix("article:")


# ---------------------------------------------------------------------------
# Per-step DB-centric phases
# ---------------------------------------------------------------------------


def _run_classify(  # noqa: PLR0912, PLR0913, PLR0915, C901
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    db: SQLiteRepository,
    digest_id: str,
    result: PipelineRunResult,
    *,
    debug_step: str | None = None,
) -> None:
    """Classify articles: query DB -> batch -> agent -> verdicts -> DB."""
    pf_logger = get_run_logger()
    articles = db.get_unclassified_articles(digest_id)
    if not articles:
        pf_logger.info("[classify] No unclassified articles — skipping")
        return

    batches = split_into_classify_batches(articles, inp.preferences)
    debug_max = int(os.getenv("NEWS_RECAP_CLASSIFY_MAX_BATCHES", "0")) or None
    if debug_max:
        batches = batches[:debug_max]
    n_batches = len(batches)
    pf_logger.info("[classify] %d articles -> %d batch(es)", len(articles), n_batches)

    all_verdicts: dict[str, str] = {}
    failed_batches = 0

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

        input_hash = compute_input_hash(pdir, task_id)
        cached = check_cached_output(pdir, task_id, input_hash)

        try:
            if not cached:
                save_input_hash(pdir, task_id, input_hash)
                run_agent_step.with_options(task_run_name=task_id)(
                    pipeline_dir=str(pdir),
                    step_name="recap_classify",
                    task_id=task_id,
                )
            else:
                pf_logger.info("[classify] Reusing cached output for batch %d", i + 1)

            verdicts_path = pdir / task_id / "output" / "agent_stdout.log"
            kept, enrich = parse_classify_batch_stdout(verdicts_path, batch)
            batch_verdicts: dict[str, str] = {}
            kept_set = set(kept)
            enrich_set = set(enrich)
            for entry in batch:
                aid = _source_id_to_article_id(entry.source_id)
                if entry.source_id in enrich_set:
                    batch_verdicts[aid] = "enrich"
                elif entry.source_id in kept_set:
                    batch_verdicts[aid] = "ok"
                else:
                    batch_verdicts[aid] = "trash"

            if debug_step == "classify":
                all_verdicts.update(batch_verdicts)
            else:

                def _commit_batch(s: "Session", v: dict[str, str] = batch_verdicts) -> None:  # type: ignore[name-defined]  # noqa: F821
                    db.save_verdicts(s, v)

                commit_with_retry(db.engine, _commit_batch)

            result.steps.append(PipelineStepResult(f"classify batch {i + 1}", task_id, "completed"))
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

    if debug_step == "classify" and all_verdicts:

        def _debug_write(session: "Session") -> None:  # type: ignore[name-defined]  # noqa: F821
            db.save_verdicts(session, all_verdicts)
            raise DebugStopError("classify")

        commit_with_retry(db.engine, _debug_write)


def _run_enrich(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    db: SQLiteRepository,
    digest_id: str,
    result: PipelineRunResult,
    *,
    debug_step: str | None = None,
) -> None:
    """Enrich articles needing enrichment."""
    pf_logger = get_run_logger()
    articles = db.get_articles_needing_enrichment(digest_id)
    if not articles:
        pf_logger.info("[enrich] No articles need enrichment — skipping")
        return

    article_entries = to_article_index(articles)
    resource_files = load_resources(article_entries)

    task_id = materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_enrich",
        article_entries=article_entries,
        extra_input_files=resource_files,
    )

    input_hash = compute_input_hash(pdir, task_id)
    cached = check_cached_output(pdir, task_id, input_hash)

    if not cached:
        save_input_hash(pdir, task_id, input_hash)
        run_agent_step.with_options(task_run_name=task_id)(
            pipeline_dir=str(pdir),
            step_name="recap_enrich",
            task_id=task_id,
        )
    else:
        pf_logger.info("[enrich] Reusing cached output")

    enriched = parse_enrich_result(read_task_output(pdir, task_id))
    pf_logger.info("Enrich: %d articles enriched", len(enriched))
    result.steps.append(PipelineStepResult("recap_enrich", task_id, "completed"))

    def _write(session: "Session") -> None:  # type: ignore[name-defined]  # noqa: F821
        db.save_enrichments(session, enriched)
        if debug_step == "enrich":
            raise DebugStopError("enrich")

    commit_with_retry(db.engine, _write)


def _run_group(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    db: SQLiteRepository,
    digest_id: str,
    result: PipelineRunResult,
    *,
    debug_step: str | None = None,
) -> None:
    """Group kept articles into events."""
    pf_logger = get_run_logger()
    if db.count_events_for_digest(digest_id) > 0:
        pf_logger.info("[group] Events already exist — skipping")
        return

    kept = db.get_kept_articles(digest_id)
    if not kept:
        pf_logger.info("[group] No kept articles — skipping")
        return

    article_entries = to_article_index(kept)
    task_id = materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_group",
        article_entries=article_entries,
    )

    input_hash = compute_input_hash(pdir, task_id)
    cached = check_cached_output(pdir, task_id, input_hash)

    if not cached:
        save_input_hash(pdir, task_id, input_hash)
        run_agent_step.with_options(task_run_name=task_id)(
            pipeline_dir=str(pdir),
            step_name="recap_group",
            task_id=task_id,
        )
    else:
        pf_logger.info("[group] Reusing cached output")

    events = parse_group_result(read_task_output(pdir, task_id))
    pf_logger.info("Group: %d events identified", len(events))
    result.steps.append(PipelineStepResult("recap_group", task_id, "completed"))

    def _write(session: "Session") -> None:  # type: ignore[name-defined]  # noqa: F821
        db.save_events(session, digest_id, events)
        if debug_step == "group":
            raise DebugStopError("group")

    commit_with_retry(db.engine, _write)


def _run_deep_enrich(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    db: SQLiteRepository,
    digest_id: str,
    result: PipelineRunResult,
    *,
    debug_step: str | None = None,
) -> None:
    """Deep-enrich significant event articles needing full text."""
    pf_logger = get_run_logger()
    all_events = db.get_all_events(digest_id)
    significant_event_ids = [
        e.event_id
        for e in all_events
        if e.significance in ("high", "medium")
        or len(db.get_event_article_ids(e.event_id)) >= MIN_ARTICLES_FOR_SIGNIFICANT_EVENT
    ]
    articles = db.get_articles_needing_full_text(digest_id, significant_event_ids)
    if not articles:
        pf_logger.info("[deep-enrich] No articles need full text — skipping")
        return

    article_entries = to_article_index(articles)
    resource_files = load_resources(article_entries)
    if not resource_files:
        pf_logger.info("[deep-enrich] No resources loaded — skipping")
        return

    task_id = materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_enrich_full",
        article_entries=article_entries,
        extra_input_files=resource_files,
    )

    input_hash = compute_input_hash(pdir, task_id)
    cached = check_cached_output(pdir, task_id, input_hash)

    if not cached:
        save_input_hash(pdir, task_id, input_hash)
        run_agent_step.with_options(task_run_name=task_id)(
            pipeline_dir=str(pdir),
            step_name="recap_enrich_full",
            task_id=task_id,
        )
    else:
        pf_logger.info("[deep-enrich] Reusing cached output")

    enriched = parse_enrich_result(read_task_output(pdir, task_id))
    pf_logger.info("Deep-enrich: %d articles enriched", len(enriched))
    result.steps.append(PipelineStepResult("recap_enrich_full", task_id, "completed"))

    def _write(session: "Session") -> None:  # type: ignore[name-defined]  # noqa: F821
        db.save_enrichments(session, enriched)
        if debug_step == "deep-enrich":
            raise DebugStopError("deep-enrich")

    commit_with_retry(db.engine, _write)


def _run_synthesize(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    db: SQLiteRepository,
    digest_id: str,
    result: PipelineRunResult,
    *,
    debug_step: str | None = None,
) -> None:
    """Synthesize narratives for events that don't have one yet."""
    pf_logger = get_run_logger()
    events = db.get_events_needing_narrative(digest_id)
    if not events:
        pf_logger.info("[synthesize] All events have narratives — skipping")
        return

    kept = db.get_kept_articles(digest_id)
    article_entries = to_article_index(kept)

    synth_resources: dict[str, bytes | str] = {}
    for event in events:
        article_ids = db.get_event_article_ids(event.event_id)
        event_data = {
            "event_id": event.event_id,
            "title": event.title,
            "significance": event.significance,
            "article_ids": [f"article:{aid}" for aid in article_ids],
        }
        synth_resources[f"event_{event.event_id}.json"] = json.dumps(
            event_data,
            ensure_ascii=False,
            indent=2,
        )

    task_id = materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_synthesize",
        article_entries=article_entries,
        extra_input_files=synth_resources,
    )

    input_hash = compute_input_hash(pdir, task_id)
    cached = check_cached_output(pdir, task_id, input_hash)

    if not cached:
        save_input_hash(pdir, task_id, input_hash)
        run_agent_step.with_options(task_run_name=task_id)(
            pipeline_dir=str(pdir),
            step_name="recap_synthesize",
            task_id=task_id,
        )
    else:
        pf_logger.info("[synthesize] Reusing cached output")

    result.steps.append(PipelineStepResult("recap_synthesize", task_id, "completed"))

    results_dir = pdir / task_id / "output" / "results"
    narratives: dict[str, str] = {}
    for event in events:
        event_file = results_dir / f"event_{event.event_id}.json"
        if event_file.exists():
            event_result = json.loads(event_file.read_text("utf-8"))
            narrative = event_result.get("synthesis") or event_result.get("narrative", "")
            if narrative:
                narratives[event.event_id] = narrative

    pf_logger.info("Synthesize: %d narratives produced", len(narratives))

    def _write(session: "Session") -> None:  # type: ignore[name-defined]  # noqa: F821
        db.save_narratives(session, narratives)
        if debug_step == "synthesize":
            raise DebugStopError("synthesize")

    commit_with_retry(db.engine, _write)


def _run_compose(  # noqa: PLR0913
    pdir: Path,
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    db: SQLiteRepository,
    digest_id: str,
    result: PipelineRunResult,
    *,
    debug_step: str | None = None,
) -> dict[str, Any]:
    """Compose the final digest from events with narratives."""
    pf_logger = get_run_logger()
    digest = db.get_digest(digest_id)
    if digest is not None and digest.status == "ready":
        pf_logger.info("[compose] Digest already ready — skipping")
        return {}

    all_events = db.get_all_events(digest_id)
    if not all_events:
        pf_logger.info("[compose] No events — skipping")
        return {}

    kept = db.get_kept_articles(digest_id)
    article_entries = to_article_index(kept)

    synth_resources: dict[str, bytes | str] = {}
    for event in all_events:
        article_ids = db.get_event_article_ids(event.event_id)
        event_data = {
            "event_id": event.event_id,
            "title": event.title,
            "significance": event.significance,
            "narrative": event.narrative or "",
            "article_ids": [f"article:{aid}" for aid in article_ids],
        }
        synth_resources[f"event_{event.event_id}.json"] = json.dumps(
            event_data,
            ensure_ascii=False,
            indent=2,
        )

    task_id = materialize_step(
        workdir_mgr,
        inp,
        step_name="recap_compose",
        article_entries=article_entries,
        extra_input_files=synth_resources,
    )

    input_hash = compute_input_hash(pdir, task_id)
    cached = check_cached_output(pdir, task_id, input_hash)

    if not cached:
        save_input_hash(pdir, task_id, input_hash)
        run_agent_step.with_options(task_run_name=task_id)(
            pipeline_dir=str(pdir),
            step_name="recap_compose",
            task_id=task_id,
        )
    else:
        pf_logger.info("[compose] Reusing cached output")

    output = read_task_output(pdir, task_id)
    result.steps.append(PipelineStepResult("recap_compose", task_id, "completed"))

    blocks = _extract_blocks_from_compose(output)

    def _write(session: "Session") -> None:  # type: ignore[name-defined]  # noqa: F821
        db.save_digest_blocks(session, digest_id, blocks)
        db.set_digest_status(session, digest_id, "ready")
        if debug_step == "compose":
            raise DebugStopError("compose")

    commit_with_retry(db.engine, _write)
    return output


def _extract_blocks_from_compose(output: dict[str, Any]) -> list[dict[str, object]]:
    """Turn compose output (theme_blocks) into flat digest blocks."""

    blocks: list[dict[str, object]] = []
    for theme in output.get("theme_blocks", []):
        theme_name = theme.get("theme", "")
        for recap_item in theme.get("recaps", []):
            source_ids = [s.get("url", "") for s in recap_item.get("sources", [])]
            headline = recap_item.get("headline", "")
            body = recap_item.get("body", "")
            text = f"**{theme_name}**: {headline}\n\n{body}"
            blocks.append({"text": text, "source_ids": source_ids})
    return blocks


# ---------------------------------------------------------------------------
# Flow entry point
# ---------------------------------------------------------------------------

_STEP_ORDER = ["classify", "enrich", "group", "deep-enrich", "synthesize", "compose"]


def _flow_run_name(
    business_date: str = "",  # noqa: ARG001
    **_kwargs: Any,
) -> str:
    now = datetime.now(tz=UTC).strftime("%H:%M:%S")
    return f"recap {business_date} {now}"


@flow(name="recap_pipeline", flow_run_name=_flow_run_name)
def recap_flow(  # noqa: PLR0913
    pipeline_dir: str,
    business_date: str,
    db_path: str,
    digest_id: str,
    user_id: str = "default_user",
    debug_step: str | None = None,
    stop_after: str | None = None,
    classify_only: bool = False,
) -> PipelineRunResult:
    """Top-level Prefect flow for the DB-centric recap pipeline."""
    from uuid import uuid4

    pf_logger = get_run_logger()
    pdir = Path(pipeline_dir)
    inp = read_pipeline_input(pipeline_dir)
    workdir_mgr = TaskWorkdirManager(pdir)

    db = SQLiteRepository(
        db_path=Path(db_path),
        user_id=user_id,
    )

    pipeline_id = str(uuid4())
    bd = date.fromisoformat(business_date)
    result = PipelineRunResult(pipeline_id=pipeline_id, business_date=bd)
    pf_logger.info("Pipeline starting: digest=%s, date=%s", digest_id, business_date)

    step_fns = {
        "classify": lambda: _run_classify(
            pdir,
            workdir_mgr,
            inp,
            db,
            digest_id,
            result,
            debug_step=debug_step,
        ),
        "enrich": lambda: _run_enrich(
            pdir,
            workdir_mgr,
            inp,
            db,
            digest_id,
            result,
            debug_step=debug_step,
        ),
        "group": lambda: _run_group(
            pdir,
            workdir_mgr,
            inp,
            db,
            digest_id,
            result,
            debug_step=debug_step,
        ),
        "deep-enrich": lambda: _run_deep_enrich(
            pdir,
            workdir_mgr,
            inp,
            db,
            digest_id,
            result,
            debug_step=debug_step,
        ),
        "synthesize": lambda: _run_synthesize(
            pdir,
            workdir_mgr,
            inp,
            db,
            digest_id,
            result,
            debug_step=debug_step,
        ),
        "compose": lambda: _run_compose(
            pdir,
            workdir_mgr,
            inp,
            db,
            digest_id,
            result,
            debug_step=debug_step,
        ),
    }

    try:
        for step_name in _STEP_ORDER:
            if classify_only and step_name != "classify":
                break

            step_fns[step_name]()

            if stop_after == step_name:
                pf_logger.info("Stopping after %s (--stop-after)", step_name)
                break

        result.status = "completed"
        pf_logger.info("Pipeline completed")

    except DebugStopError as exc:
        result.status = "debug_stopped"
        pf_logger.info("Pipeline debug-stopped at %s (DB rolled back)", exc)
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
    finally:
        db.close()

    return result
