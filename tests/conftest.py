"""Shared test fixtures."""

from __future__ import annotations

import sys
from dataclasses import replace

import pytest

from news_recap.config import Settings

_ECHO_AGENT_COMMAND_TEMPLATE = (
    f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent --prompt-file {{prompt_file}}"
)


@pytest.fixture()
def echo_agent(monkeypatch):
    """Monkeypatch Settings.from_env to use the echo agent for codex."""
    original_from_env = Settings.from_env

    def _patched_from_env(db_path=None):
        settings = original_from_env(db_path=db_path)
        new_orch = replace(
            settings.orchestrator, codex_command_template=_ECHO_AGENT_COMMAND_TEMPLATE
        )
        return replace(settings, orchestrator=new_orch)

    monkeypatch.setattr(Settings, "from_env", staticmethod(_patched_from_env))
