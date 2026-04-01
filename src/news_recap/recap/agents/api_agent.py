"""Execute an LLM call via direct SDK transport (API execution backend).

Reads the task prompt from the pre-materialized workdir, calls the transport,
and writes the response content to ``output/agent_stdout.log`` so that all
downstream ``parse_fn`` implementations work unchanged.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path

from news_recap.recap.agents.concurrency import ConcurrencyController
from news_recap.recap.agents.transport import (
    LLMTransport,
    TransportOverloadedError,
    TransportRateLimitError,
)
from news_recap.recap.contracts import read_task_input
from news_recap.recap.tasks.base import RecapPipelineError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120
_BASE_BACKOFF = 1.0


def run_api_agent(  # noqa: PLR0913
    pipeline_dir: str,
    step_name: str,
    task_id: str,
    model: str,
    transport: LLMTransport,
    concurrency_controller: ConcurrencyController,
    timeout: int,
    max_backoff: float,
    jitter: float,
    stop_event: threading.Event | None = None,
) -> str:
    """Call LLM via transport API and write the response to ``agent_stdout.log``.

    Returns *task_id* on success; raises ``RecapPipelineError`` on failure.
    """
    task_dir = Path(pipeline_dir) / task_id
    task_input_path = task_dir / "input" / "task_input.json"
    task_input = read_task_input(task_input_path)
    prompt = task_input.prompt

    stdout_path = task_dir / "output" / "agent_stdout.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)

    step_start = time.monotonic()
    attempt = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            raise RecapPipelineError(step_name, "Pipeline interrupted by user")

        concurrency_controller.acquire(stop_event)
        try:
            response = transport.complete(model=model, prompt=prompt, timeout=timeout)
        except (TransportRateLimitError, TransportOverloadedError) as exc:
            concurrency_controller.release()
            logger.warning(
                "[cyan]%s:[/cyan] rate limit / overload (attempt %d): %s",
                step_name,
                attempt,
                exc,
            )
            concurrency_controller.on_rate_limit()
            backoff = min(_BASE_BACKOFF * (2**attempt), max_backoff)
            sleep_time = backoff + random.uniform(0, jitter)  # noqa: S311
            logger.info("[cyan]%s:[/cyan] retrying in %.1fs", step_name, sleep_time)
            if stop_event is not None:
                stop_event.wait(sleep_time)
            else:
                time.sleep(sleep_time)
            attempt += 1
            continue
        except Exception as exc:
            concurrency_controller.release()
            raise RecapPipelineError(step_name, f"API call failed: {exc}") from exc
        else:
            concurrency_controller.on_success()
            concurrency_controller.release()
            break

    elapsed = time.monotonic() - step_start
    total_tokens = response.input_tokens + response.output_tokens

    m, s = divmod(int(elapsed), 60)
    t = f"{m}m {s}s" if m else f"{elapsed:.1f}s"
    logger.info(
        "[green]✓[/green] [cyan]%s:[/cyan] Finished in %s tokens=%s",
        step_name,
        t,
        f"{total_tokens:,}",
    )

    stdout_path.write_text(response.content, "utf-8")

    usage = {
        "elapsed_seconds": round(elapsed, 1),
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": total_tokens,
        "model": model,
        "provider": "anthropic",
        "finish_reason": response.finish_reason,
        "retries": attempt,
        "backend": "api",
    }
    usage_path = task_dir / "meta" / "usage.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(json.dumps(usage), "utf-8")

    return task_id
