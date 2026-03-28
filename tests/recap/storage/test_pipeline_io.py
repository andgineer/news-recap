"""Tests for PipelineInput deserialization backward compatibility."""

from __future__ import annotations

import json
from pathlib import Path


from news_recap.recap.storage.pipeline_io import read_pipeline_input
from news_recap.recap.tasks.prompts import PromptBackend


def _write_pipeline_input(tmp_path: Path, extra: dict | None = None) -> Path:
    """Write a minimal pipeline_input.json (without optional new fields)."""
    payload = {
        "business_date": "2026-01-01",
        "articles": [],
        "preferences": {
            "exclude": "",
            "follow": "",
            "language": "en",
        },
        "routing_defaults": {
            "default_agent": "codex",
            "task_model_map": {
                "recap_classify": {"codex": "--model gpt-5.2"},
            },
            "task_type_timeout_map": {"recap_classify": 600},
            "command_templates": {
                "codex": 'codex {model} "Read {prompt_file}"',
                "claude": 'claude {model} -- "Read {prompt_file}"',
                "gemini": 'gemini {model} "Read {prompt_file}"',
            },
        },
        "agent_override": None,
        "data_dir": ".news_recap_data",
    }
    if extra:
        payload.update(extra)
    path = tmp_path / "pipeline_input.json"
    path.write_text(json.dumps(payload), "utf-8")
    return tmp_path


def test_read_pipeline_input_old_format_defaults_to_cli(tmp_path):
    """Old pipeline_input.json without execution_backend defaults to cli backend."""
    pipeline_dir = _write_pipeline_input(tmp_path)
    inp = read_pipeline_input(str(pipeline_dir))
    assert inp.execution_backend == "cli"
    assert inp.prompt_backend == PromptBackend.CLI


def test_read_pipeline_input_with_execution_backend_api(tmp_path):
    """New pipeline_input.json with execution_backend=api is read correctly."""
    pipeline_dir = _write_pipeline_input(
        tmp_path,
        extra={
            "routing_defaults": {
                "default_agent": "claude",
                "task_model_map": {},
                "task_type_timeout_map": {"recap_classify": 120},
                "command_templates": {
                    "codex": 'codex {model} "Read {prompt_file}"',
                    "claude": 'claude {model} -- "Read {prompt_file}"',
                    "gemini": 'gemini {model} "Read {prompt_file}"',
                },
                "execution_backend": "api",
                "api_model_map": {"recap_classify": "claude-haiku-4-5-20251001"},
            },
        },
    )
    inp = read_pipeline_input(str(pipeline_dir))
    assert inp.execution_backend == "api"
    assert inp.prompt_backend == PromptBackend.API
