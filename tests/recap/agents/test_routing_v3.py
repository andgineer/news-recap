"""Tests for routing schema v3 (execution_backend field)."""

from __future__ import annotations

import pytest

from news_recap.recap.agents.routing import (
    ROUTING_SCHEMA_VERSION,
    RoutingDefaults,
    _parse_frozen_routing,
    resolve_routing_for_enqueue,
)


assert ROUTING_SCHEMA_VERSION == 3, "bump this test if schema version changes"


def _api_defaults(api_model_map: dict[str, str] | None = None) -> RoutingDefaults:
    return RoutingDefaults(
        default_agent="claude",
        task_model_map={},
        task_type_timeout_map={"recap_classify": 120},
        command_templates={
            "claude": 'claude {model} -- "Read {prompt_file}"',
            "codex": 'codex {model} "Read {prompt_file}"',
            "gemini": 'gemini {model} "Read {prompt_file}"',
        },
        execution_backend="api",
        api_model_map=api_model_map
        or {
            "recap_classify": "claude-haiku-4-5-20251001",
            "recap_reduce": "claude-sonnet-4-6",
        },
    )


def _cli_defaults() -> RoutingDefaults:
    return RoutingDefaults(
        default_agent="codex",
        task_model_map={
            "recap_classify": {
                "codex": "--model gpt-5.2",
                "claude": "--model sonnet",
                "gemini": "--model gemini-2.5-flash",
            },
        },
        task_type_timeout_map={"recap_classify": 120},
        command_templates={
            "claude": 'claude {model} -- "Read {prompt_file}"',
            "codex": 'codex {model} "Read {prompt_file}"',
            "gemini": 'gemini {model} "Read {prompt_file}"',
        },
        execution_backend="cli",
    )


# ---------------------------------------------------------------------------
# Schema v3 — new frozen routing fields
# ---------------------------------------------------------------------------


def test_resolve_routing_api_sets_empty_command_template():
    routing = resolve_routing_for_enqueue(
        defaults=_api_defaults(),
        task_type="recap_classify",
        agent_override=None,
        model_override=None,
    )
    assert routing.execution_backend == "api"
    assert routing.command_template == ""
    assert routing.model == "claude-haiku-4-5-20251001"
    assert routing.schema_version == ROUTING_SCHEMA_VERSION


def test_resolve_routing_cli_has_non_empty_command_template():
    routing = resolve_routing_for_enqueue(
        defaults=_cli_defaults(),
        task_type="recap_classify",
        agent_override=None,
        model_override=None,
    )
    assert routing.execution_backend == "cli"
    assert routing.command_template != ""


def test_resolve_routing_api_rejects_codex_agent_override():
    with pytest.raises(ValueError, match="requires agent=claude.*got agent=codex"):
        resolve_routing_for_enqueue(
            defaults=_api_defaults(),
            task_type="recap_classify",
            agent_override="codex",
            model_override=None,
        )


def test_resolve_routing_api_rejects_gemini_agent_override():
    with pytest.raises(ValueError, match="requires agent=claude.*got agent=gemini"):
        resolve_routing_for_enqueue(
            defaults=_api_defaults(),
            task_type="recap_classify",
            agent_override="gemini",
            model_override=None,
        )


def test_resolve_routing_api_raises_on_missing_api_model():
    defaults = _api_defaults(api_model_map={"recap_reduce": "claude-sonnet-4-6"})
    with pytest.raises(ValueError, match="No API model configured for task_type="):
        resolve_routing_for_enqueue(
            defaults=defaults,
            task_type="recap_classify",
            agent_override=None,
            model_override=None,
        )


# ---------------------------------------------------------------------------
# _parse_frozen_routing — version migration
# ---------------------------------------------------------------------------


def _base_raw(schema_version: int, **extra) -> dict:
    return {
        "schema_version": schema_version,
        "agent": "codex",
        "model": "--model gpt-5.2",
        "command_template": 'codex {model} "Read {prompt_file}"',
        "resolved_at": "2026-01-01T00:00:00+00:00",
        "resolved_by": "enqueue",
        **extra,
    }


def test_parse_frozen_routing_v1_defaults_cli():
    parsed = _parse_frozen_routing(_base_raw(1))
    assert parsed is not None
    assert parsed.execution_backend == "cli"
    assert parsed.schema_version == ROUTING_SCHEMA_VERSION


def test_parse_frozen_routing_v2_defaults_cli():
    parsed = _parse_frozen_routing(_base_raw(2))
    assert parsed is not None
    assert parsed.execution_backend == "cli"


def test_parse_frozen_routing_v3_reads_execution_backend():
    raw = _base_raw(3, execution_backend="cli")
    parsed = _parse_frozen_routing(raw)
    assert parsed is not None
    assert parsed.execution_backend == "cli"


def test_parse_frozen_routing_v3_api_allows_empty_command_template():
    raw = {
        "schema_version": 3,
        "agent": "claude",
        "model": "claude-haiku-4-5-20251001",
        "command_template": "",
        "resolved_at": "2026-01-01T00:00:00+00:00",
        "resolved_by": "enqueue",
        "execution_backend": "api",
    }
    parsed = _parse_frozen_routing(raw)
    assert parsed is not None
    assert parsed.execution_backend == "api"
    assert parsed.command_template == ""


def test_parse_frozen_routing_rejects_unknown_version():
    raw = _base_raw(99)
    parsed = _parse_frozen_routing(raw)
    assert parsed is None


def test_parse_frozen_routing_rejects_cli_with_empty_command_template():
    raw = _base_raw(3, execution_backend="cli", command_template="")
    parsed = _parse_frozen_routing(raw)
    assert parsed is None


def test_parse_frozen_routing_rejects_api_with_non_empty_command_template():
    raw = {
        "schema_version": 3,
        "agent": "claude",
        "model": "claude-haiku",
        "command_template": "claude --model {model} -- {prompt_file}",
        "resolved_at": "2026-01-01T00:00:00+00:00",
        "resolved_by": "enqueue",
        "execution_backend": "api",
    }
    parsed = _parse_frozen_routing(raw)
    assert parsed is None
