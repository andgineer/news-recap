"""Task launcher: group kept articles into thematic events."""

from __future__ import annotations

from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.storage.pipeline_io import materialize_step, read_task_output
from news_recap.recap.storage.schemas import RECAP_GROUP_OUTPUT_SCHEMA
from news_recap.recap.tasks.base import PipelineStepResult, TaskLauncher
from news_recap.recap.tasks.prompts import RECAP_GROUP_PROMPT

# ---------------------------------------------------------------------------
# Group-specific helpers
# ---------------------------------------------------------------------------


def parse_group_result(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return events list from group output."""
    return payload.get("events", [])


def merge_enriched_into_index(
    entries: list[ArticleIndexEntry],
    enriched: dict[str, dict[str, str]],
) -> list[ArticleIndexEntry]:
    """Update article titles from enrichment pass."""
    result: list[ArticleIndexEntry] = []
    for entry in entries:
        enriched_data = enriched.get(entry.source_id)
        if enriched_data and enriched_data.get("new_title"):
            result.append(
                ArticleIndexEntry(
                    source_id=entry.source_id,
                    title=enriched_data["new_title"],
                    url=entry.url,
                    source=entry.source,
                    published_at=entry.published_at,
                ),
            )
        else:
            result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Task launcher
# ---------------------------------------------------------------------------


class Group(TaskLauncher):
    """Cluster kept articles into thematic events via LLM."""

    name = "group"

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        kept_entries = ctx.state["kept_entries"]
        enriched_articles = ctx.state.get("enriched_articles", {})
        enriched_entries = merge_enriched_into_index(kept_entries, enriched_articles)

        tid = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_group",
            article_entries=enriched_entries,
            prompt=RECAP_GROUP_PROMPT,
            schema_hint=RECAP_GROUP_OUTPUT_SCHEMA,
        )
        tid = run_ai_agent.with_options(task_run_name=tid)(
            pipeline_dir=str(ctx.pdir),
            step_name="recap_group",
            task_id=tid,
        )
        ctx.result.steps.append(PipelineStepResult("recap_group", tid, "completed"))
        events = parse_group_result(read_task_output(ctx.pdir, tid))
        pf_logger.info("Group: %d events identified", len(events))
        ctx.state["events"] = events
