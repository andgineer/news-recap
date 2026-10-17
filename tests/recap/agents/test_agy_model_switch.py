"""Tests for switching Antigravity to a listed Flash model when agy rejects the configured one."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_recap.recap.agents import ai_agent
from news_recap.recap.agents.ai_agent import _cheapest_flash_model, run_ai_agent
from news_recap.recap.exceptions import RecapPipelineError

OLD_FLAGS = "--model gemini-3.7-flash --effort low"
NEW_FLAGS = "--model gemini-3.8-flash-low"

# `agy models` output from 2026-10-17.
AGY_MODELS = """\
Fetching available models...
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)
gemini-3.8-flash-low\tGemini 3.8 Flash (Low)
claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)
claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""

REJECTED = {
    "status": "ERROR",
    "response": "",
    "error": 'invalid model selection (--model "gemini-3.7-flash" --effort "low"): '
    '--effort is not supported for model "gemini-3.7-flash"',
    "usage": {"input_tokens": 0, "total_tokens": 0},
}
ANSWERED = {
    "status": "SUCCESS",
    "response": "1: ok\n",
    "usage": {"input_tokens": 11887, "total_tokens": 11888},
}


@pytest.fixture(autouse=True)
def _fresh_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_agent, "_agy_model_switches", {})


def _list_models(stdout: str):
    return patch.object(
        ai_agent.subprocess,
        "run",
        return_value=SimpleNamespace(stdout=stdout, returncode=0),
    )


def test_picks_lowest_effort_flash_from_real_listing() -> None:
    with _list_models(AGY_MODELS):
        assert _cheapest_flash_model("agy") == "gemini-3.8-flash-low"


def test_lower_effort_beats_newer_version() -> None:
    listing = "gemini-3.9-flash-medium\tA\ngemini-3.8-flash-low\tB\n"
    with _list_models(listing):
        assert _cheapest_flash_model("agy") == "gemini-3.8-flash-low"


def test_newest_flash_wins_at_equal_effort() -> None:
    listing = "gemini-3.8-flash-low\tA\ngemini-3.10-flash-low\tB\n"
    with _list_models(listing):
        assert _cheapest_flash_model("agy") == "gemini-3.10-flash-low"


def test_plain_flash_preferred_over_lite() -> None:
    listing = "gemini-3.9-flash-lite-low\tA\ngemini-3.9-flash-low\tB\n"
    with _list_models(listing):
        assert _cheapest_flash_model("agy") == "gemini-3.9-flash-low"


def test_name_without_effort_ranks_as_medium() -> None:
    listing = "gemini-4.0-flash\tA\ngemini-3.9-flash-high\tB\n"
    with _list_models(listing):
        assert _cheapest_flash_model("agy") == "gemini-4.0-flash"


def test_no_flash_model_listed() -> None:
    with _list_models("claude-sonnet-4-6\tClaude\n"):
        assert _cheapest_flash_model("agy") is None


@pytest.mark.parametrize("error", [OSError("no agy"), subprocess.TimeoutExpired("agy", 60)])
def test_listing_failure_gives_no_model(error: Exception) -> None:
    with patch.object(ai_agent.subprocess, "run", side_effect=error):
        assert _cheapest_flash_model("agy") is None


def _fake_launch(tmp_path: Path, envelopes: list[dict], launched: list[str]):
    """Fake ``_run_agent_cli`` that answers each launch with the next agy envelope."""
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)

    def launch(*, model: str, **_kw):
        launched.append(model)
        envelope = envelopes[len(launched) - 1]
        stdout = out / "agent_stdout.log"
        stderr = out / "agent_stderr.log"
        stdout.write_text(json.dumps(envelope), "utf-8")
        stderr.write_text("agy log\n", "utf-8")
        return SimpleNamespace(
            exit_code=0 if envelope["status"] == "SUCCESS" else 1,
            timed_out=False,
            stdout_path=stdout,
            stderr_path=stderr,
        )

    return launch


def _run(tmp_path: Path, launch, cheapest: MagicMock) -> str:
    routing = SimpleNamespace(
        agent="antigravity",
        model=OLD_FLAGS,
        command_template="agy {model} -p task",
        execution_backend="cli",
        extra_env=None,
    )
    inp = MagicMock()
    inp.routing_defaults.task_type_timeout_map = {}
    inp.routing_defaults.agent_api_key_vars = {}
    with (
        patch.object(ai_agent, "read_manifest"),
        patch.object(ai_agent, "read_pipeline_input", return_value=inp),
        patch.object(ai_agent, "resolve_routing_for_enqueue", return_value=routing),
        patch.object(ai_agent, "_run_agent_cli", side_effect=launch),
        patch.object(ai_agent, "_cheapest_flash_model", cheapest),
    ):
        return run_ai_agent(str(tmp_path), "recap_enrich", "enrich-1")


def test_rejected_model_is_switched_and_launch_retried(tmp_path: Path) -> None:
    launched: list[str] = []
    cheapest = MagicMock(return_value="gemini-3.8-flash-low")
    launch = _fake_launch(tmp_path, [REJECTED, ANSWERED, ANSWERED], launched)

    assert _run(tmp_path, launch, cheapest) == "enrich-1"
    assert launched == [OLD_FLAGS, NEW_FLAGS]
    assert (tmp_path / "out" / "agent_stdout.log").read_text("utf-8") == "1: ok\n"

    _run(tmp_path, launch, cheapest)
    assert launched == [OLD_FLAGS, NEW_FLAGS, NEW_FLAGS]
    cheapest.assert_called_once_with("agy")


def test_no_flash_model_keeps_the_rejection(tmp_path: Path) -> None:
    launched: list[str] = []
    launch = _fake_launch(tmp_path, [REJECTED], launched)

    with pytest.raises(RecapPipelineError, match="Invalid model/effort selection"):
        _run(tmp_path, launch, MagicMock(return_value=None))
    assert launched == [OLD_FLAGS]


def test_rejected_replacement_is_not_retried_again(tmp_path: Path) -> None:
    launched: list[str] = []
    launch = _fake_launch(tmp_path, [REJECTED, REJECTED], launched)

    with pytest.raises(RecapPipelineError, match="Invalid model/effort selection"):
        _run(tmp_path, launch, MagicMock(return_value="gemini-3.8-flash-low"))
    assert launched == [OLD_FLAGS, NEW_FLAGS]


def test_listed_model_equal_to_rejected_is_not_retried(tmp_path: Path) -> None:
    launched: list[str] = []
    launch = _fake_launch(tmp_path, [REJECTED], launched)
    same_as_rejected = OLD_FLAGS.removeprefix("--model ")

    with pytest.raises(RecapPipelineError):
        _run(tmp_path, launch, MagicMock(return_value=same_as_rejected))
    assert launched == [OLD_FLAGS]
