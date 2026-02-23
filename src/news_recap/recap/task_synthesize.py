"""Task launcher: synthesize event narratives via LLM."""

from __future__ import annotations

from typing import Any

from news_recap.recap.pipeline_io import materialize_step
from news_recap.recap.runner import PipelineStepResult, events_to_resource_files
from news_recap.recap.task_ai_agent import run_ai_agent
from news_recap.recap.task_base import TaskLauncher


class Synthesize(TaskLauncher):
    """Generate narrative summaries for each event via LLM."""

    name = "synthesize"

    def execute(self) -> None:
        ctx = self.ctx
        kept_entries = ctx.state["kept_entries"]
        event_payloads: list[dict[str, Any]] = ctx.state["event_payloads"]
        synth_resources = events_to_resource_files(event_payloads)

        tid = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_synthesize",
            article_entries=kept_entries,
            extra_input_files=synth_resources,
        )
        tid = run_ai_agent.with_options(task_run_name=tid)(
            pipeline_dir=str(ctx.pdir),
            step_name="recap_synthesize",
            task_id=tid,
        )
        ctx.result.steps.append(PipelineStepResult("recap_synthesize", tid, "completed"))
        ctx.state["synth_resources"] = synth_resources
