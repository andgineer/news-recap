from __future__ import annotations

import allure

from news_recap.config import OrchestratorSettings
from news_recap.recap.contracts import TaskInputContract
from news_recap.recap.agents.routing import (
    ROUTING_SCHEMA_VERSION,
    RoutingDefaults,
    resolve_routing_for_enqueue,
    resolve_routing_for_execution,
)

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Routing, Failures, CLI Ops"),
]


def _defaults() -> RoutingDefaults:
    return RoutingDefaults(
        default_agent="codex",
        task_model_map={
            "highlights": {
                "codex": "codex-highlights",
                "claude": "claude-highlights",
                "gemini": "gemini-highlights",
            },
            "story": {
                "codex": "codex-story",
                "claude": "claude-story",
                "gemini": "gemini-story",
            },
        },
        task_type_timeout_map={
            "highlights": 600,
            "story": 900,
        },
        command_templates={
            "claude": 'claude --model {model} -- "Read task from {prompt_file}"',
            "codex": 'codex exec --model {model} "Read task from {prompt_file}"',
            "gemini": 'gemini --model {model} --prompt "Read task from {prompt_file}"',
        },
    )


def test_resolve_routing_uses_task_model_map_override() -> None:
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="story",
        agent_override=None,
        model_override=None,
    )
    assert routing.agent == "codex"
    assert routing.model == "codex-story"
    assert routing.schema_version == ROUTING_SCHEMA_VERSION
    assert routing.resolved_by == "enqueue"


def test_resolve_routing_uses_highlights_model() -> None:
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="highlights",
        agent_override=None,
        model_override=None,
    )
    assert routing.agent == "codex"
    assert routing.model == "codex-highlights"


def test_resolve_routing_respects_agent_and_model_overrides() -> None:
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="highlights",
        agent_override="gemini",
        model_override="gemini-custom",
    )
    assert routing.agent == "gemini"
    assert routing.model == "gemini-custom"
    assert "gemini --model" in routing.command_template


def test_resolve_routing_for_execution_uses_frozen_metadata() -> None:
    frozen = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="story",
        agent_override="claude",
        model_override="claude-custom",
    )
    task_input = TaskInputContract(
        task_type="story",
        prompt="hello",
        metadata={"routing": frozen.to_metadata()},
    )
    resolved, fallback_reason = resolve_routing_for_execution(
        task_input=task_input,
        task_type="story",
        defaults=_defaults(),
    )
    assert fallback_reason is None
    assert resolved.agent == "claude"
    assert resolved.model == "claude-custom"


def test_resolve_routing_for_execution_applies_fallback_on_missing_metadata() -> None:
    task_input = TaskInputContract(task_type="highlights", prompt="x", metadata={})
    resolved, fallback_reason = resolve_routing_for_execution(
        task_input=task_input,
        task_type="highlights",
        defaults=_defaults(),
    )
    assert fallback_reason is not None
    assert resolved.agent == "codex"
    assert resolved.model == "codex-highlights"
    assert resolved.resolved_by == "worker_fallback"


def test_routing_defaults_rejects_antigravity_as_default() -> None:
    settings = OrchestratorSettings(default_agent="antigravity")
    try:
        RoutingDefaults.from_settings(settings)
    except ValueError as error:
        assert "antigravity" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected antigravity default to be rejected.")


def test_resolve_routing_task_model_map_overrides_default_for_agent() -> None:
    """task_model_map resolves the correct model for agent+task."""
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="story",
        agent_override="claude",
        model_override=None,
    )
    assert routing.model == "claude-story"


def test_resolve_routing_gemini_uses_task_model_map() -> None:
    """All agents are explicitly listed in task_model_map."""
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="story",
        agent_override="gemini",
        model_override=None,
    )
    assert routing.model == "gemini-story"


def test_resolve_routing_raises_on_missing_task_type() -> None:
    """Unknown task_type raises ValueError (no silent fallback)."""
    try:
        resolve_routing_for_enqueue(
            defaults=_defaults(),
            task_type="unknown_task",
            agent_override=None,
            model_override=None,
        )
    except ValueError as error:
        assert "unknown_task" in str(error)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for unknown task_type")
