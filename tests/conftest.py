"""Shared test fixtures."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_recap.config import Settings
from news_recap.recap.models import UserPreferences

_ECHO_AGENT_COMMAND_TEMPLATE = (
    f"{sys.executable} -m news_recap.recap.agents.echo --prompt-file {{prompt_file}}"
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path_factory):
    # The developer's settings and Jev key (~/.news_recap_data, ./.env, the shell) must not
    # reach tests.
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.fixture()
def write_config():
    """Write ``config.toml`` into the test's isolated data dir."""

    def write(text: str) -> Path:
        path = Path(os.environ["NEWS_RECAP_DATA_DIR"]) / "config.toml"
        path.write_text(text, "utf-8")
        return path

    return write


@pytest.fixture()
def echo_agent(monkeypatch):
    """Monkeypatch Settings.load to use the echo agent for codex."""
    original_load = Settings.load

    def _patched_load(**kwargs):
        settings = original_load(**kwargs)
        new_orch = replace(
            settings.orchestrator, codex_command_template=_ECHO_AGENT_COMMAND_TEMPLATE
        )
        return replace(settings, orchestrator=new_orch)

    monkeypatch.setattr(Settings, "load", staticmethod(_patched_load))


def make_settings_mock(tmp_path: Path) -> MagicMock:
    """Build a ``MagicMock`` mimicking ``Settings.load()`` for controller tests."""
    settings = MagicMock()
    settings.orchestrator.workdir_root = tmp_path / "workdirs"
    settings.orchestrator.default_agent = "codex"
    settings.orchestrator.task_model_map = {}
    settings.orchestrator.claude_command_template = ""
    settings.orchestrator.codex_command_template = ""
    settings.orchestrator.antigravity_command_template = ""
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
    settings.jev.model = "jev-1.13.0"
    settings.jev.classify_backend = "llm"
    settings.jev.dedup_backend = "llm"
    settings.preferences = UserPreferences()
    return settings
