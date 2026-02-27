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
from news_recap.recap.models import UserPreferences
from news_recap.recap.storage.pipeline_io import PipelineInput

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


# --- effective_max_parallel ------------------------------------------------


def _pipeline_input(
    agent_override: str | None = None,
    agent_max_parallel: dict[str, int] | None = None,
) -> PipelineInput:
    rd = _defaults()
    if agent_max_parallel is not None:
        rd = RoutingDefaults(
            default_agent=rd.default_agent,
            task_model_map=rd.task_model_map,
            task_type_timeout_map=rd.task_type_timeout_map,
            command_templates=rd.command_templates,
            agent_max_parallel=agent_max_parallel,
        )
    return PipelineInput(
        articles=[],
        preferences=UserPreferences.from_dict({}),
        routing_defaults=rd,
        agent_override=agent_override,
        data_dir=".news_recap_data",
        business_date="2026-02-19",
    )


def test_effective_max_parallel_codex_default() -> None:
    """Codex has no agent_max_parallel cap — returns task_max."""
    inp = _pipeline_input()
    assert inp.effective_max_parallel(5) == 5


def test_effective_max_parallel_claude_capped() -> None:
    """Claude agent_max_parallel=2 caps task_max=5 to 2."""
    inp = _pipeline_input(
        agent_override="claude",
        agent_max_parallel={"claude": 2, "codex": 5},
    )
    assert inp.effective_max_parallel(5) == 2


def test_effective_max_parallel_task_max_lower() -> None:
    """When task_max < vendor cap, task_max wins."""
    inp = _pipeline_input(
        agent_override="codex",
        agent_max_parallel={"codex": 10},
    )
    assert inp.effective_max_parallel(3) == 3


def test_effective_max_parallel_unknown_agent_returns_task_max() -> None:
    """Unknown agent not in agent_max_parallel falls back to task_max."""
    inp = _pipeline_input(agent_override="codex", agent_max_parallel={})
    assert inp.effective_max_parallel(4) == 4


def test_effective_max_parallel_uses_default_agent_when_no_override() -> None:
    """When agent_override is None, default_agent ('codex') is used."""
    inp = _pipeline_input(
        agent_override=None,
        agent_max_parallel={"codex": 2},
    )
    assert inp.effective_max_parallel(5) == 2
