"""Tests for _run_agent_cli environment variable handling."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from news_recap.recap.agents.ai_agent import _run_agent_cli
from news_recap.recap.agents.subprocess import SubprocessResult
from news_recap.recap.contracts import TaskInputContract, TaskManifest


def _make_manifest(tmp_path: Path) -> TaskManifest:
    """Write minimal task files and return a manifest pointing at them."""
    workdir = tmp_path / "task"
    workdir.mkdir()

    input_dir = workdir / "input"
    input_dir.mkdir()
    contract = TaskInputContract(task_type="recap_classify", prompt="Test prompt")
    (input_dir / "task_input.json").write_text(json.dumps(asdict(contract)), "utf-8")

    output_dir = workdir / "output"
    output_dir.mkdir()

    return TaskManifest(
        contract_version=1,
        task_id="test-task",
        task_type="recap_classify",
        workdir=str(workdir),
        task_input_path=str(input_dir / "task_input.json"),
        articles_index_path=str(input_dir / "articles_index.json"),
        output_result_path=str(output_dir / "result.json"),
        output_stdout_path=str(output_dir / "stdout.txt"),
        output_stderr_path=str(output_dir / "stderr.txt"),
    )


def _fake_result(manifest: TaskManifest) -> SubprocessResult:
    return SubprocessResult(
        exit_code=0,
        timed_out=False,
        stdout_path=Path(manifest.output_stdout_path),
        stderr_path=Path(manifest.output_stderr_path),
    )


@pytest.fixture()
def manifest(tmp_path: Path) -> TaskManifest:
    return _make_manifest(tmp_path)


def _run_and_capture_env(manifest: TaskManifest, **kwargs) -> dict[str, str]:
    """Run _run_agent_cli with a mocked subprocess and return the env passed to it."""
    captured: dict[str, str] = {}

    def fake_run_subprocess(**kw):
        captured.update(kw["env"])
        return _fake_result(manifest)

    with patch("news_recap.recap.agents.ai_agent.run_subprocess", side_effect=fake_run_subprocess):
        _run_agent_cli(
            manifest=manifest,
            timeout_seconds=10,
            command_template="echo {model} -- {prompt_file}",
            model="test-model",
            **kwargs,
        )
    return captured


# ---------------------------------------------------------------------------
# Default behaviour: API keys are removed
# ---------------------------------------------------------------------------


def test_api_keys_removed_by_default(manifest, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    env = _run_and_capture_env(manifest, api_key_vars=["ANTHROPIC_API_KEY"])
    assert "ANTHROPIC_API_KEY" not in env


def test_multiple_api_keys_removed(manifest, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "secret-google")
    env = _run_and_capture_env(manifest, api_key_vars=["GEMINI_API_KEY", "GOOGLE_API_KEY"])
    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env


def test_unset_key_missing_from_env_is_not_an_error(manifest):
    """Removing a key that was never set must not raise."""
    env = _run_and_capture_env(manifest, api_key_vars=["ANTHROPIC_API_KEY"])
    assert "ANTHROPIC_API_KEY" not in env


# ---------------------------------------------------------------------------
# use_api_key=True: keys are preserved
# ---------------------------------------------------------------------------


def test_api_key_preserved_when_use_api_key_true(manifest, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    env = _run_and_capture_env(manifest, api_key_vars=["ANTHROPIC_API_KEY"], use_api_key=True)
    assert env.get("ANTHROPIC_API_KEY") == "secret-anthropic"


def test_no_api_key_vars_leaves_env_unchanged(manifest, monkeypatch):
    """Empty api_key_vars must not remove anything even when use_api_key=False."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    env = _run_and_capture_env(manifest, api_key_vars=[])
    assert env.get("ANTHROPIC_API_KEY") == "secret-anthropic"
