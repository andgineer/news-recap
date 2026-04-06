"""Shared test fixtures."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_recap.config import Settings

_ECHO_AGENT_COMMAND_TEMPLATE = (
    f"{sys.executable} -m news_recap.recap.agents.echo --prompt-file {{prompt_file}}"
)


@pytest.fixture()
def echo_agent(monkeypatch):
    """Monkeypatch Settings.from_env to use the echo agent for codex."""
    original_from_env = Settings.from_env

    def _patched_from_env(**kwargs):
        settings = original_from_env(**kwargs)
        new_orch = replace(
            settings.orchestrator, codex_command_template=_ECHO_AGENT_COMMAND_TEMPLATE
        )
        return replace(settings, orchestrator=new_orch)

    monkeypatch.setattr(Settings, "from_env", staticmethod(_patched_from_env))


def make_settings_mock(tmp_path: Path) -> MagicMock:
    """Build a ``MagicMock`` mimicking ``Settings.from_env()`` for controller tests."""
    settings = MagicMock()
    settings.orchestrator.workdir_root = tmp_path / "workdirs"
    settings.orchestrator.default_agent = "codex"
    settings.orchestrator.task_model_map = {}
    settings.orchestrator.claude_command_template = ""
    settings.orchestrator.codex_command_template = ""
    settings.orchestrator.gemini_command_template = ""
    settings.orchestrator.task_type_timeout_map = {}
    settings.orchestrator.agent_max_parallel = {}
    settings.orchestrator.agent_launch_delay = {}
    settings.orchestrator.execution_backend = "cli"
    settings.orchestrator.api_model_map = {}
    settings.orchestrator.api_max_parallel = 4
    settings.orchestrator.api_concurrency_recovery_successes = 3
    settings.orchestrator.api_downshift_pause_seconds = 5.0
    settings.orchestrator.api_retry_max_backoff_seconds = 60.0
    settings.orchestrator.api_retry_jitter_seconds = 1.0
    settings.orchestrator.agent_api_key_vars = {}
    settings.data_dir = tmp_path / "data"
    settings.ingestion.gc_retention_days = 30
    settings.ingestion.digest_lookback_days = 7
    settings.ingestion.min_resource_chars = 200
    settings.dedup.threshold = 0.90
    settings.dedup.model_name = "intfloat/multilingual-e5-small"
    return settings
