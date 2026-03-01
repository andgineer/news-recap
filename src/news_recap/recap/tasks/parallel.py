"""Shared windowed parallel execution for pipeline steps.

All parallel steps (classify, enrich, map, etc.) share the same pattern:
submit batches in windows of ``max_parallel``, collect results, and stop
after the current window on the first failure.  This module centralises
that logic so each step only supplies *prepare* and *parse* callbacks.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from news_recap.recap.agents.ai_agent import read_agent_usage, run_ai_agent
from news_recap.recap.tasks.base import (
    FlowContext,
    RecapPipelineError,
)


def submit_and_collect(  # noqa: PLR0913, C901
    ctx: FlowContext,
    items: list,
    *,
    step_name: str,
    step_label: str,
    start_batch: int,
    max_parallel: int,
    prepare_fn: Callable[[Any, int], str],
    parse_fn: Callable[[str, Any, int], Any],
    logger: Any,
) -> tuple[list, int, int]:
    """Submit work items in parallel windows, collect results, stop on failure.

    Parameters
    ----------
    ctx:
        Flow context — used for ``ctx.pdir`` (pipeline dir).
    items:
        Work items (batches / chunks) to process.
    step_name:
        Step name passed to ``run_ai_agent`` (e.g. ``"recap_classify"``).
    step_label:
        Human-readable label for log messages (e.g. ``"classify batch"``).
    start_batch:
        Batch counter origin; the first item uses ``start_batch + 1``.
    max_parallel:
        Maximum number of concurrent threads per window.
    prepare_fn(item, batch_num) -> task_id:
        Materialise the task workdir and return the task id.
        May raise ``RecapPipelineError`` to mark the item as failed.
    parse_fn(task_id, item, batch_num) -> result:
        Parse the agent output and return a step-specific result object.
        May raise ``RecapPipelineError`` to mark the item as failed.
    logger:
        Logger instance.

    Returns
    -------
    (results, n_failed, last_batch_num)
        *results* contains one entry per successful item.
        *n_failed* is the count of items that raised ``RecapPipelineError``.
        *last_batch_num* is the final batch counter value (for multi-round
        callers like enrich).
    """
    n_failed = 0
    results: list = []
    batch_num = start_batch
    completed_task_ids: list[str] = []
    launch_delay = ctx.inp.launch_delay
    stop_event = threading.Event()

    def _run_with_delay(delay: float, **kwargs: Any) -> str:
        if delay > 0 and stop_event.wait(delay):
            raise RecapPipelineError("interrupted", "Pipeline interrupted by user")
        return run_ai_agent(**kwargs, stop_event=stop_event)

    executor = ThreadPoolExecutor(max_workers=max_parallel)
    try:
        for window_start in range(0, len(items), max_parallel):
            window = items[window_start : window_start + max_parallel]

            futures: list[tuple[int, Any, Any, str]] = []
            prepare_exc: Exception | None = None
            for idx, item in enumerate(window):
                batch_num += 1
                try:
                    task_id = prepare_fn(item, batch_num)
                except RecapPipelineError as exc:
                    logger.error("%s %d: preparation failed: %s", step_label, batch_num, exc)
                    n_failed += 1
                    break
                except Exception as exc:
                    logger.exception("%s %d: preparation failed", step_label, batch_num)
                    prepare_exc = exc
                    break
                future = executor.submit(
                    _run_with_delay,
                    delay=idx * launch_delay,
                    pipeline_dir=str(ctx.pdir),
                    step_name=step_name,
                    task_id=task_id,
                )
                futures.append((batch_num, item, future, task_id))

            for bnum, item, future, orig_tid in futures:
                resolved_tid = orig_tid
                try:
                    resolved_tid = future.result()
                    result = parse_fn(resolved_tid, item, bnum)
                    results.append(result)
                except RecapPipelineError as exc:
                    logger.error("%s %d failed: %s", step_label, bnum, exc)
                    n_failed += 1
                completed_task_ids.append(resolved_tid)

            if prepare_exc is not None:
                raise prepare_exc

            if n_failed > 0:
                break

        executor.shutdown(wait=True)
    except KeyboardInterrupt:
        stop_event.set()
        executor.shutdown(wait=True, cancel_futures=True)
        raise

    _log_total_tokens(ctx, step_name, completed_task_ids, logger)
    return results, n_failed, batch_num


def _log_total_tokens(
    ctx: FlowContext,
    step_name: str,
    task_ids: list[str],
    logger: Any,
) -> None:
    """Sum tokens from completed agent runs and log the total."""
    total = 0
    for tid in task_ids:
        _, tokens = read_agent_usage(ctx.pdir / tid)
        total += tokens
    if total:
        logger.info("[%s] total tokens: %s", step_name, f"{total:,}")
