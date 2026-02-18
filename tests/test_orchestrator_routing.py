from __future__ import annotations

from news_recap.config import OrchestratorSettings
from news_recap.orchestrator.contracts import TaskInputContract
from news_recap.orchestrator.routing import (
    ROUTING_SCHEMA_VERSION,
    RoutingDefaults,
    resolve_routing_for_enqueue,
    resolve_routing_for_execution,
)


def _defaults() -> RoutingDefaults:
    return RoutingDefaults(
        default_agent="codex",
        task_type_profile_map={
            "highlights": "fast",
            "story": "quality",
        },
        command_templates={
            "claude": "claude --model {model} -- {prompt}",
            "codex": "codex exec --model {model} {prompt}",
            "gemini": "gemini --model {model} --prompt {prompt}",
        },
        models={
            "claude": {"fast": "claude-fast", "quality": "claude-quality"},
            "codex": {"fast": "codex-fast", "quality": "codex-quality"},
            "gemini": {"fast": "gemini-fast", "quality": "gemini-quality"},
        },
    )


def test_resolve_routing_for_enqueue_uses_task_type_profile() -> None:
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="story",
        agent_override=None,
        profile_override=None,
        model_override=None,
    )
    assert routing.agent == "codex"
    assert routing.profile == "quality"
    assert routing.model == "codex-quality"
    assert routing.schema_version == ROUTING_SCHEMA_VERSION
    assert routing.resolved_by == "enqueue"


def test_resolve_routing_for_enqueue_respects_overrides() -> None:
    routing = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="highlights",
        agent_override="gemini",
        profile_override="fast",
        model_override="gemini-custom",
    )
    assert routing.agent == "gemini"
    assert routing.profile == "fast"
    assert routing.model == "gemini-custom"
    assert "gemini --model" in routing.command_template


def test_resolve_routing_for_execution_uses_frozen_metadata() -> None:
    frozen = resolve_routing_for_enqueue(
        defaults=_defaults(),
        task_type="highlights",
        agent_override="claude",
        profile_override="quality",
        model_override="claude-custom",
    )
    task_input = TaskInputContract(
        task_type="highlights",
        prompt="hello",
        metadata={"routing": frozen.to_metadata()},
    )
    resolved, fallback_reason = resolve_routing_for_execution(
        task_input=task_input,
        task_type="highlights",
        defaults=_defaults(),
    )
    assert fallback_reason is None
    assert resolved.agent == "claude"
    assert resolved.profile == "quality"
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
    assert resolved.profile == "fast"
    assert resolved.model == "codex-fast"
    assert resolved.resolved_by == "worker_fallback"


def test_routing_defaults_rejects_antigravity_as_default() -> None:
    settings = OrchestratorSettings(default_agent="antigravity")
    try:
        RoutingDefaults.from_settings(settings)
    except ValueError as error:
        assert "antigravity" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected antigravity default to be rejected.")
