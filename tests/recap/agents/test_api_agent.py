"""Tests for run_api_agent."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_recap.recap.agents.concurrency import ConcurrencyController
from news_recap.recap.agents.transport import (
    LLMResponse,
    TransportRateLimitError,
)
from news_recap.recap.tasks.base import RecapPipelineError


def _make_cc(cap: int = 5) -> ConcurrencyController:
    return ConcurrencyController(
        initial_cap=cap,
        recovery_successes=10,
        downshift_pause=0.0,
        max_backoff=1.0,
        jitter=0.0,
    )


def _make_transport(content: str = "OK response") -> MagicMock:
    transport = MagicMock()
    transport.complete.return_value = LLMResponse(
        content=content,
        input_tokens=100,
        output_tokens=50,
        finish_reason="end_turn",
    )
    return transport


def _setup_task_dir(tmp_path: Path, prompt: str = "test prompt") -> tuple[Path, str]:
    """Create a minimal task workdir and return (pipeline_dir, task_id)."""
    task_id = "classify-1"
    task_dir = tmp_path / task_id
    (task_dir / "input").mkdir(parents=True)
    (task_dir / "output").mkdir(parents=True)
    (task_dir / "meta").mkdir(parents=True)

    task_input = {
        "task_type": "recap_classify",
        "prompt": prompt,
        "metadata": {},
    }
    (task_dir / "input" / "task_input.json").write_text(json.dumps(task_input), "utf-8")
    return tmp_path, task_id


def test_happy_path_writes_stdout_and_usage(tmp_path):
    from news_recap.recap.agents.api_agent import run_api_agent

    pipeline_dir, task_id = _setup_task_dir(tmp_path)
    transport = _make_transport("great answer")
    cc = _make_cc()

    result = run_api_agent(
        pipeline_dir=str(pipeline_dir),
        step_name="recap_classify",
        task_id=task_id,
        model="claude-haiku-4-5-20251001",
        transport=transport,
        concurrency_controller=cc,
        timeout=30,
        max_backoff=1.0,
        jitter=0.0,
    )

    assert result == task_id
    stdout = (pipeline_dir / task_id / "output" / "agent_stdout.log").read_text("utf-8")
    assert stdout == "great answer"

    usage_data = json.loads((pipeline_dir / task_id / "meta" / "usage.json").read_text())
    assert usage_data["input_tokens"] == 100
    assert usage_data["output_tokens"] == 50
    assert usage_data["total_tokens"] == 150
    assert usage_data["model"] == "claude-haiku-4-5-20251001"
    assert usage_data["provider"] == "anthropic"
    assert usage_data["finish_reason"] == "end_turn"
    assert usage_data["retries"] == 0
    assert usage_data["backend"] == "api"


def test_rate_limit_triggers_on_rate_limit_and_retries(tmp_path):
    from news_recap.recap.agents.api_agent import run_api_agent

    pipeline_dir, task_id = _setup_task_dir(tmp_path)
    cc = _make_cc()
    transport = MagicMock()

    ok_response = LLMResponse("ok", 10, 5, "end_turn")
    transport.complete.side_effect = [
        TransportRateLimitError("rate limited"),
        ok_response,
    ]

    with patch("time.sleep"):  # skip actual sleep
        result = run_api_agent(
            pipeline_dir=str(pipeline_dir),
            step_name="recap_classify",
            task_id=task_id,
            model="claude-haiku-4-5-20251001",
            transport=transport,
            concurrency_controller=cc,
            timeout=30,
            max_backoff=60.0,
            jitter=0.0,
        )

    assert result == task_id
    assert transport.complete.call_count == 2

    usage = json.loads((pipeline_dir / task_id / "meta" / "usage.json").read_text())
    assert usage["retries"] == 1


def test_backoff_respects_max_backoff_ceiling(tmp_path):
    from news_recap.recap.agents.api_agent import run_api_agent

    pipeline_dir, task_id = _setup_task_dir(tmp_path)
    cc = _make_cc()
    transport = MagicMock()
    ok_response = LLMResponse("ok", 10, 5, "end_turn")

    # Fail 3 times, succeed on 4th
    transport.complete.side_effect = [
        TransportRateLimitError("r"),
        TransportRateLimitError("r"),
        TransportRateLimitError("r"),
        ok_response,
    ]

    sleep_calls: list[float] = []
    with patch("time.sleep", side_effect=lambda t: sleep_calls.append(t)):
        run_api_agent(
            pipeline_dir=str(pipeline_dir),
            step_name="recap_classify",
            task_id=task_id,
            model="m",
            transport=transport,
            concurrency_controller=cc,
            timeout=30,
            max_backoff=2.0,
            jitter=0.0,
        )

    # All backoff sleeps must be <= max_backoff
    # (sleep_calls also includes cc.on_rate_limit downshift_pause=0, so filter > 0)
    backoff_sleeps = [s for s in sleep_calls if s > 0]
    assert all(s <= 2.0 for s in backoff_sleeps)


def test_stop_event_raises_recap_pipeline_error(tmp_path):
    from news_recap.recap.agents.api_agent import run_api_agent

    pipeline_dir, task_id = _setup_task_dir(tmp_path)
    cc = _make_cc()
    transport = MagicMock()

    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RecapPipelineError, match="interrupted"):
        run_api_agent(
            pipeline_dir=str(pipeline_dir),
            step_name="recap_classify",
            task_id=task_id,
            model="m",
            transport=transport,
            concurrency_controller=cc,
            timeout=30,
            max_backoff=1.0,
            jitter=0.0,
            stop_event=stop_event,
        )


def test_non_rate_limit_exception_raises_recap_pipeline_error(tmp_path):
    from news_recap.recap.agents.api_agent import run_api_agent

    pipeline_dir, task_id = _setup_task_dir(tmp_path)
    cc = _make_cc()
    transport = MagicMock()
    transport.complete.side_effect = RuntimeError("connection error")

    with pytest.raises(RecapPipelineError, match="API call failed"):
        run_api_agent(
            pipeline_dir=str(pipeline_dir),
            step_name="recap_classify",
            task_id=task_id,
            model="m",
            transport=transport,
            concurrency_controller=cc,
            timeout=30,
            max_backoff=1.0,
            jitter=0.0,
        )
