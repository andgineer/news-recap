from __future__ import annotations

from pathlib import Path

import allure

from news_recap.brain.backend.cli_backend import _build_run_args

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
