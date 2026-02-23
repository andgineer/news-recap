"""Task launcher: compose the final digest document."""

from __future__ import annotations

from typing import Any

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.runner import PipelineStepResult, events_to_resource_files
from news_recap.recap.storage.pipeline_io import materialize_step, read_task_output
from news_recap.recap.tasks.base import TaskLauncher


class Compose(TaskLauncher):
    """Assemble the final digest document from synthesized event narratives."""

    name = "compose"

    def execute(self) -> None:
        ctx = self.ctx
        kept_entries = ctx.state["kept_entries"]
        event_payloads: list[dict[str, Any]] = ctx.state["event_payloads"]
        synth_resources = ctx.state.get("synth_resources") or events_to_resource_files(
            event_payloads,
        )

        tid = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_compose",
            article_entries=kept_entries,
            extra_input_files=synth_resources,
        )
        tid = run_ai_agent.with_options(task_run_name=tid)(
            pipeline_dir=str(ctx.pdir),
            step_name="recap_compose",
            task_id=tid,
        )
        ctx.result.steps.append(PipelineStepResult("recap_compose", tid, "completed"))
        ctx.result.digest = read_task_output(ctx.pdir, tid)
