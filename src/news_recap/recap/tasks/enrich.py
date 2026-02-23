"""Task launchers: enrich articles via LLM with loaded full-text resources.

Two pipeline steps share the same enrichment core:

* ``Enrich`` — enriches articles flagged by classify as needing more context.
* ``EnrichFull`` — deep-enriches articles from significant events, then
  builds event payloads for downstream synthesis.
"""

from __future__ import annotations

from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.runner import (
    PipelineStepResult,
    articles_needing_full_text,
    build_event_payloads,
    parse_enrich_result,
    select_significant_events,
)
from news_recap.recap.storage.pipeline_io import load_resources, materialize_step, read_task_output
from news_recap.recap.tasks.base import FlowContext, TaskLauncher


def _run_enrich(
    ctx: FlowContext,
    *,
    step_name: str,
    article_entries: list[ArticleIndexEntry],
    resource_entries: list[ArticleIndexEntry],
) -> dict[str, dict[str, str]]:
    """Shared enrichment: load resources, run agent, parse result."""
    pf_logger = get_run_logger()
    loaded = load_resources(resource_entries)

    if not loaded:
        pf_logger.info("[%s] No resources loaded — skipping agent call", step_name)
        return {}

    tid = materialize_step(
        ctx.workdir_mgr,
        ctx.inp,
        step_name=step_name,
        article_entries=article_entries,
        extra_input_files=loaded,
    )
    tid = run_ai_agent.with_options(task_run_name=tid)(
        pipeline_dir=str(ctx.pdir),
        step_name=step_name,
        task_id=tid,
    )
    ctx.result.steps.append(PipelineStepResult(step_name, tid, "completed"))
    enriched = parse_enrich_result(read_task_output(ctx.pdir, tid))
    pf_logger.info("[%s] %d articles enriched", step_name, len(enriched))
    return enriched


class Enrich(TaskLauncher):
    """Fetch full text for articles flagged ``enrich`` by classify and re-run them."""

    name = "enrich"

    def execute(self) -> None:
        ctx = self.ctx
        enrich_ids: list[str] = ctx.state.get("enrich_ids", [])
        kept_entries = ctx.state["kept_entries"]
        resource_entries = [ctx.article_map[sid] for sid in enrich_ids if sid in ctx.article_map]

        ctx.result.steps.append(PipelineStepResult("resource_load", None, "completed"))
        ctx.state["enriched_articles"] = _run_enrich(
            ctx,
            step_name="recap_enrich",
            article_entries=kept_entries,
            resource_entries=resource_entries,
        )


class EnrichFull(TaskLauncher):
    """Select significant events, load full article text, and enrich via LLM.

    Produces ``event_payloads`` by merging both enrichment passes.
    """

    name = "enrich_full"

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        events: list[dict[str, Any]] = ctx.state["events"]
        enriched_articles: dict[str, dict[str, str]] = ctx.state.get("enriched_articles", {})

        significant = select_significant_events(events)
        articles_for_full = articles_needing_full_text(significant, ctx.article_map)
        pf_logger.info(
            "Significant events: %d, articles needing full text: %d",
            len(significant),
            len(articles_for_full),
        )

        enriched_full = _run_enrich(
            ctx,
            step_name="recap_enrich_full",
            article_entries=articles_for_full,
            resource_entries=articles_for_full,
        )

        ctx.state["event_payloads"] = build_event_payloads(
            events,
            enriched_articles,
            enriched_full,
            ctx.article_map,
        )
