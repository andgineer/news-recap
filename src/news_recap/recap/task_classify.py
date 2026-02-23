"""Task launcher: batch-classify articles into ok / enrich / trash."""

from __future__ import annotations

import os
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.pipeline_io import materialize_step
from news_recap.recap.runner import (
    PipelineStepResult,
    RecapPipelineError,
    build_classify_batch_prompt,
    parse_classify_batch_stdout,
    split_into_classify_batches,
)
from news_recap.recap.task_ai_agent import run_ai_agent
from news_recap.recap.task_base import TaskLauncher

_MIN_BATCH_SUCCESS_RATE = 0.8


class Classify(TaskLauncher):
    """Split articles into batches and ask the LLM to verdict each as ok / enrich / trash."""

    name = "classify"

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        batches = split_into_classify_batches(ctx.inp.articles, ctx.inp.preferences)
        debug_max = int(os.getenv("NEWS_RECAP_CLASSIFY_MAX_BATCHES", "0")) or None
        if debug_max:
            batches = batches[:debug_max]
        n_batches = len(batches)
        pf_logger.info("[classify] %d articles -> %d batch(es)", len(ctx.inp.articles), n_batches)

        futures: list[tuple[int, list[Any], Any]] = []
        for i, batch in enumerate(batches):
            prompt = build_classify_batch_prompt(batch, ctx.inp.preferences)
            task_id = materialize_step(
                ctx.workdir_mgr,
                ctx.inp,
                step_name="recap_classify",
                batch=i + 1,
                prompt=prompt,
            )
            pf_logger.info("[classify] Batch %d/%d — %d headlines", i + 1, n_batches, len(batch))
            future = run_ai_agent.with_options(task_run_name=task_id).submit(
                pipeline_dir=str(ctx.pdir),
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
                verdicts_path = ctx.pdir / tid / "output" / "agent_stdout.log"
                kept, enrich = parse_classify_batch_stdout(verdicts_path, batch)
                all_kept.extend(kept)
                all_enrich.extend(enrich)
                ctx.result.steps.append(
                    PipelineStepResult(f"classify batch {i + 1}", tid, "completed"),
                )
            except Exception:  # noqa: BLE001
                pf_logger.exception("classify batch %d failed", i + 1)
                failed_batches += 1
                ctx.result.steps.append(
                    PipelineStepResult(f"classify batch {i + 1}", None, "failed"),
                )

        if failed_batches > 0:
            success_rate = (n_batches - failed_batches) / n_batches
            if success_rate < _MIN_BATCH_SUCCESS_RATE:
                raise RecapPipelineError(
                    "recap_classify",
                    f"Too many batch failures: {failed_batches}/{n_batches} failed",
                )
            pf_logger.warning(
                "[classify] %d/%d batches failed — partial results",
                failed_batches,
                n_batches,
            )

        ctx.state["kept_entries"] = [
            ctx.article_map[sid] for sid in all_kept if sid in ctx.article_map
        ]
        ctx.state["enrich_ids"] = all_enrich
        pf_logger.info(
            "Classify: %d kept, %d discarded, %d need enrichment",
            len(all_kept),
            len(ctx.inp.articles) - len(all_kept),
            len(all_enrich),
        )
