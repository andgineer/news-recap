"""Shared test fixtures."""

from __future__ import annotations

import sys
from concurrent.futures import Future
from dataclasses import replace
from functools import wraps

import pytest

from news_recap.config import Settings

_ECHO_AGENT_COMMAND_TEMPLATE = (
    f"{sys.executable} -m news_recap.recap.backend.echo_agent --prompt-file {{prompt_file}}"
)


class _FakeTaskWrapper:
    """Mimics Prefect task API (.with_options, .submit) using a plain function."""

    def __init__(self, fn):
        self._fn = fn
        wraps(fn)(self)

    def __call__(self, *args, **kwargs):
        return self._fn(*args, **kwargs)

    def with_options(self, **_kwargs):
        return self

    def submit(self, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(self._fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


@pytest.fixture(autouse=True)
def _bypass_prefect(monkeypatch):
    """Replace @flow/@task decorated functions with their raw .fn so tests
    never start a Prefect ephemeral server or bind to a port."""
    from news_recap.recap import agent_task, flow

    for mod in (agent_task, flow):
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if callable(obj) and hasattr(obj, "fn"):
                raw = obj.fn
                monkeypatch.setattr(mod, name, _FakeTaskWrapper(raw))


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
