"""Tests for routing schema v3 (execution_backend field)."""

from __future__ import annotations

import pytest

from news_recap.recap.agents.routing import (
    ROUTING_SCHEMA_VERSION,
    RoutingDefaults,
    _parse_frozen_routing,
    resolve_routing_for_enqueue,
)


assert ROUTING_SCHEMA_VERSION == 4, "bump this test if schema version changes"


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
            "recap_oneshot_digest": "claude-haiku-4-5-20251001",
        },
    )


def _cli_defaults() -> RoutingDefaults:
    return RoutingDefaults(
        default_agent="codex",
        task_model_map={
            "recap_classify": {
                "codex": {"model": "--model gpt-5.2"},
                "claude": {"model": "--model sonnet", "env": {"MAX_THINKING_TOKENS": "0"}},
                "gemini": {"model": "--model gemini-2.5-flash"},
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
    defaults = _api_defaults(api_model_map={"recap_oneshot_digest": "claude-haiku-4-5-20251001"})
    with pytest.raises(ValueError, match="No API model configured for task_type="):
        resolve_routing_for_enqueue(
            defaults=defaults,
            task_type="recap_classify",
            agent_override=None,
            model_override=None,
        )


# ---------------------------------------------------------------------------
# _parse_frozen_routing
# ---------------------------------------------------------------------------


def _base_raw(**extra) -> dict:
    return {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "agent": "codex",
        "model": "--model gpt-5.2",
        "command_template": 'codex {model} "Read {prompt_file}"',
        "execution_backend": "cli",
        "resolved_at": "2026-01-01T00:00:00+00:00",
        "resolved_by": "enqueue",
        **extra,
    }


def test_parse_frozen_routing_accepts_current_version():
    parsed = _parse_frozen_routing(_base_raw())
    assert parsed is not None
    assert parsed.execution_backend == "cli"
    assert parsed.schema_version == ROUTING_SCHEMA_VERSION


def test_parse_frozen_routing_rejects_old_versions():
    for old_version in (1, 2, 3):
        assert _parse_frozen_routing(_base_raw(schema_version=old_version)) is None


def test_parse_frozen_routing_rejects_unknown_version():
    assert _parse_frozen_routing(_base_raw(schema_version=99)) is None


def test_parse_frozen_routing_api_allows_empty_command_template():
    raw = _base_raw(
        agent="claude",
        model="claude-haiku-4-5-20251001",
        command_template="",
        execution_backend="api",
    )
    parsed = _parse_frozen_routing(raw)
    assert parsed is not None
    assert parsed.execution_backend == "api"
    assert parsed.command_template == ""


def test_parse_frozen_routing_rejects_cli_with_empty_command_template():
    parsed = _parse_frozen_routing(_base_raw(command_template=""))
    assert parsed is None


def test_parse_frozen_routing_rejects_api_with_non_empty_command_template():
    raw = _base_raw(
        agent="claude",
        model="claude-haiku",
        command_template="claude --model {model} -- {prompt_file}",
        execution_backend="api",
    )
    assert _parse_frozen_routing(raw) is None


def test_parse_frozen_routing_reads_extra_env():
    raw = _base_raw(extra_env={"MAX_THINKING_TOKENS": "0"})
    parsed = _parse_frozen_routing(raw)
    assert parsed is not None
    assert parsed.extra_env == {"MAX_THINKING_TOKENS": "0"}
