"""Jev usage/answer files stay readable by the existing usage readers."""

from __future__ import annotations

import json
from pathlib import Path

from news_recap.recap.agents.ai_agent import read_agent_usage
from news_recap.recap.jev.usage import jev_task_dir, save_answers, save_jev_usage
from news_recap.recap.pipeline_setup import _aggregate_usage


def test_usage_round_trips_through_read_agent_usage(tmp_path: Path) -> None:
    task_dir = jev_task_dir(tmp_path, "classify")
    save_jev_usage(task_dir, elapsed=12.34, input_tokens=350_000, requests=420, model="jev-1.13.0")

    assert read_agent_usage(task_dir) == (12.3, 350_000)
    data = json.loads((task_dir / "meta" / "usage.json").read_text())
    assert data["backend"] == "jev"
    assert data["requests"] == 420
    assert data["model"] == "jev-1.13.0"
    assert data["cost_usd"] == 0.0147


def test_jev_dir_counted_by_run_aggregator(tmp_path: Path) -> None:
    save_jev_usage(
        jev_task_dir(tmp_path, "route"),
        elapsed=3.0,
        input_tokens=1_000,
        requests=5,
        model="jev-1.13.0",
    )
    stats = _aggregate_usage(tmp_path)
    assert (stats.elapsed, stats.tokens, stats.prompt_bytes) == (3.0, 1_000, 0)


def test_save_answers(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = [{"article_id": "a1", "p": {"t0": 0.91, "vague": 0.1}}]
    save_answers(tmp_path, rows)
    assert json.loads((tmp_path / "output" / "jev_answers.json").read_text()) == rows
    assert jev_task_dir(tmp_path, "classify").name == "classify-jev"
