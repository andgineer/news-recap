"""Task launcher: group kept articles into thematic events."""

from __future__ import annotations

from prefect.logging import get_run_logger

from news_recap.recap.pipeline_io import materialize_step, read_task_output
from news_recap.recap.runner import (
    PipelineStepResult,
    merge_enriched_into_index,
    parse_group_result,
)
from news_recap.recap.task_ai_agent import run_ai_agent
from news_recap.recap.task_base import TaskLauncher


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
