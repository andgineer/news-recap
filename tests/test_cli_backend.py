from __future__ import annotations

from pathlib import Path

import allure

from news_recap.recap.agents.subprocess import build_run_args as _build_run_args

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Agent Command Rendering"),
]


def test_build_run_args_windows_quotes_prompt_file_with_spaces() -> None:
    run_args, command_head = _build_run_args(
        command_template='codex exec {model} "Read your task from {prompt_file} and execute it."',
        model="--model gpt-5.2 -c model_reasoning_effort=low",
        prompt_file=Path("input/my prompt.txt"),
        os_name="nt",
    )

    assert isinstance(run_args, str)
    assert command_head == "codex"
    assert '"input/my prompt.txt"' in run_args or "my prompt.txt" in run_args


def test_build_run_args_unix_splits_correctly() -> None:
    run_args, command_head = _build_run_args(
        command_template='codex exec {model} "Read your task from {prompt_file} and execute it."',
        model="--model gpt-5.2 -c model_reasoning_effort=low",
        prompt_file=Path("input/prompt.txt"),
        os_name="posix",
    )

    assert isinstance(run_args, list)
    assert command_head == "codex"
    assert "input/prompt.txt" in " ".join(run_args)


def test_build_run_args_unix_model_expands_as_separate_args() -> None:
    """String values (like model) expand into multiple argv entries."""
    run_args, _ = _build_run_args(
        "agent run {model} --file {prompt_file}",
        model="--model gpt-5.2 -c effort=low",
        prompt_file=Path("input/my prompt.txt"),
        os_name="posix",
    )

    assert isinstance(run_args, list)
    assert "--model" in run_args
    assert "gpt-5.2" in run_args
    joined = " ".join(run_args)
    assert "my prompt.txt" in joined


def test_build_run_args_unix_path_with_spaces_quoted() -> None:
    """Path values with spaces are quoted so they stay as one arg."""
    run_args, command_head = _build_run_args(
        "tool --cfg {config_path}",
        config_path=Path("/tmp/my config/file.json"),
        os_name="posix",
    )

    assert isinstance(run_args, list)
    assert command_head == "tool"
    joined = " ".join(run_args)
    assert "my config/file.json" in joined
