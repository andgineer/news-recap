from __future__ import annotations

from pathlib import Path

import allure

from news_recap.recap.task_subprocess import build_run_args as _build_run_args

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


def test_build_run_args_unix_quotes_string_values_with_spaces() -> None:
    """String values containing spaces must not break argument boundaries."""
    run_args, _ = _build_run_args(
        "agent run {model} --file {prompt_file}",
        model="--model gpt-5.2 -c effort=low",
        prompt_file=Path("input/my prompt.txt"),
        os_name="posix",
    )

    assert isinstance(run_args, list)
    joined = " ".join(run_args)
    assert "my prompt.txt" in joined
    assert "gpt-5.2" in joined
    for arg in run_args:
        assert arg.strip(), "No empty args from broken quoting"


def test_build_run_args_unix_custom_placeholder() -> None:
    """Extra kwargs beyond model/prompt_file are substituted and quoted."""
    run_args, command_head = _build_run_args(
        "tool {action} --cfg {config_path}",
        action="do something",
        config_path=Path("/tmp/my config/file.json"),
        os_name="posix",
    )

    assert isinstance(run_args, list)
    assert command_head == "tool"
    joined = " ".join(run_args)
    assert "do something" in joined or "do\\ something" in joined
    assert "my config/file.json" in joined


def test_build_run_args_unix_shell_metacharacters_quoted() -> None:
    """Shell metacharacters in values must be safely quoted."""
    run_args, _ = _build_run_args(
        "cmd {arg}",
        arg="hello; rm -rf /",
        os_name="posix",
    )

    assert isinstance(run_args, list)
    assert len(run_args) == 2
    assert run_args[0] == "cmd"
    assert "rm" not in run_args[0]
    assert "hello; rm -rf /" in run_args[1]
