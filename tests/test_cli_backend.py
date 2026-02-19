from __future__ import annotations

from pathlib import Path

import allure

from news_recap.orchestrator.backend.cli_backend import _build_run_args

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Agent Command Rendering"),
]


def test_build_run_args_windows_avoids_nested_quoting_in_quoted_payload() -> None:
    run_args, command_head = _build_run_args(
        command_template='codex exec --model {model} "task_manifest={task_manifest}\\n{prompt}"',
        model="gpt-5-codex",
        prompt='hello "world"',
        prompt_file=Path("input/prompt.txt"),
        manifest_path=Path("m file.json"),
        os_name="nt",
    )

    assert isinstance(run_args, str)
    assert command_head == "codex"
    assert (
        run_args == 'codex exec --model gpt-5-codex "task_manifest=m file.json\\nhello \\"world\\""'
    )


def test_build_run_args_windows_quotes_unquoted_placeholder_values() -> None:
    run_args, command_head = _build_run_args(
        command_template="runner --manifest {task_manifest} --prompt {prompt} --model {model}",
        model="gpt-5-codex",
        prompt="hello world",
        prompt_file=Path("input/prompt.txt"),
        manifest_path=Path("m file.json"),
        os_name="nt",
    )

    assert isinstance(run_args, str)
    assert command_head == "runner"
    assert '--manifest "m file.json"' in run_args
    assert '--prompt "hello world"' in run_args
    assert "--model gpt-5-codex" in run_args
