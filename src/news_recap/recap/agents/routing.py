"""Routing resolution helpers for per-task LLM execution."""

from __future__ import annotations

from typing import Any

import msgspec

from news_recap.config import OrchestratorSettings
from news_recap.recap.contracts import TaskInputContract
from news_recap.storage.io import utc_now

SUPPORTED_AGENTS = ("claude", "codex", "gemini")
ROUTING_SCHEMA_VERSION = 2


class FrozenRouting(msgspec.Struct):
    """Resolved immutable routing payload stored in task metadata."""

    schema_version: int
    agent: str
    model: str
    command_template: str
    resolved_at: str
    resolved_by: str

    def to_metadata(self) -> dict[str, object]:
        return msgspec.structs.asdict(self)


class RoutingDefaults(msgspec.Struct):
    """Settings snapshot used for enqueue-time routing."""

    default_agent: str
    task_model_map: dict[str, dict[str, str]]
    task_type_timeout_map: dict[str, int]
    command_templates: dict[str, str]
    agent_max_parallel: dict[str, int] = msgspec.field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return msgspec.structs.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingDefaults:
        return msgspec.convert(data, RoutingDefaults)

    @classmethod
    def from_settings(cls, settings: OrchestratorSettings) -> RoutingDefaults:
        """Build validated defaults from orchestrator settings."""

        default_agent = _normalize_agent(settings.default_agent)
        _validate_supported_agent(default_agent)
        command_templates = {
            "claude": settings.claude_command_template,
            "codex": settings.codex_command_template,
            "gemini": settings.gemini_command_template,
        }
        for agent, template in command_templates.items():
            if not template.strip():
                raise ValueError(f"Empty command template for agent={agent!r}")
        return cls(
            default_agent=default_agent,
            task_model_map={
                task_type.lower(): {agent.lower(): model for agent, model in agent_models.items()}
                for task_type, agent_models in settings.task_model_map.items()
            },
            task_type_timeout_map={
                task_type.lower(): timeout
                for task_type, timeout in settings.task_type_timeout_map.items()
            },
            command_templates=command_templates,
            agent_max_parallel=dict(settings.agent_max_parallel),
        )


def _resolve_model(
    defaults: RoutingDefaults,
    task_type: str,
    agent: str,
) -> str:
    """Look up model from task_model_map[task_type][agent]."""
    task_type_key = task_type.strip().lower()
    agent_models = defaults.task_model_map.get(task_type_key)
    if agent_models is None:
        raise ValueError(
            f"No model configured for task_type={task_type_key!r}. Add it to task_model_map.",
        )
    model = agent_models.get(agent)
    if model is None:
        raise ValueError(
            f"No model configured for task_type={task_type_key!r}, agent={agent!r}. "
            f"Add it to task_model_map.",
        )
    return model


def resolve_routing_for_enqueue(
    *,
    defaults: RoutingDefaults,
    task_type: str,
    agent_override: str | None,
    model_override: str | None,
) -> FrozenRouting:
    """Resolve and freeze routing at enqueue time."""

    agent = (
        _normalize_agent(agent_override) if agent_override is not None else defaults.default_agent
    )
    _validate_supported_agent(agent)
    model = (
        model_override.strip()
        if model_override is not None
        else _resolve_model(defaults, task_type, agent)
    )
    if not model:
        raise ValueError(
            f"Resolved model is empty for agent={agent!r}, task_type={task_type!r}",
        )
    command_template = defaults.command_templates[agent].strip()
    if not command_template:
        raise ValueError(f"Resolved command template is empty for agent={agent!r}")
    return FrozenRouting(
        schema_version=ROUTING_SCHEMA_VERSION,
        agent=agent,
        model=model,
        command_template=command_template,
        resolved_at=utc_now().isoformat(),
        resolved_by="enqueue",
    )


def resolve_routing_for_execution(
    *,
    task_input: TaskInputContract,
    task_type: str,
    defaults: RoutingDefaults,
) -> tuple[FrozenRouting, str | None]:
    """Return frozen routing from metadata or deterministic fallback."""

    raw = task_input.metadata.get("routing")
    if isinstance(raw, dict):
        parsed = _parse_frozen_routing(raw)
        if parsed is not None:
            return parsed, None
        reason = "task_input.metadata.routing is invalid; applied deterministic fallback"
    else:
        reason = "task_input.metadata.routing is missing; applied deterministic fallback"

    fallback = resolve_routing_for_enqueue(
        defaults=defaults,
        task_type=task_type,
        agent_override=None,
        model_override=None,
    )
    return (
        FrozenRouting(
            schema_version=fallback.schema_version,
            agent=fallback.agent,
            model=fallback.model,
            command_template=fallback.command_template,
            resolved_at=utc_now().isoformat(),
            resolved_by="worker_fallback",
        ),
        reason,
    )


def _parse_frozen_routing(raw: dict[str, Any]) -> FrozenRouting | None:  # noqa: PLR0911
    schema_version = raw.get("schema_version")
    agent = raw.get("agent")
    model = raw.get("model")
    command_template = raw.get("command_template")
    resolved_at = raw.get("resolved_at")
    resolved_by = raw.get("resolved_by")

    if schema_version not in (ROUTING_SCHEMA_VERSION, 1):
        return None
    if not isinstance(agent, str) or not agent.strip():
        return None
    agent = _normalize_agent(agent)
    if agent not in SUPPORTED_AGENTS:
        return None
    if not isinstance(model, str) or not model.strip():
        return None
    if not isinstance(command_template, str) or not command_template.strip():
        return None
    if not isinstance(resolved_at, str) or not resolved_at.strip():
        return None
    if not isinstance(resolved_by, str) or not resolved_by.strip():
        return None

    return FrozenRouting(
        schema_version=ROUTING_SCHEMA_VERSION,
        agent=agent,
        model=model.strip(),
        command_template=command_template.strip(),
        resolved_at=resolved_at.strip(),
        resolved_by=resolved_by.strip(),
    )


def _normalize_agent(value: str) -> str:
    return value.strip().lower()


def _validate_supported_agent(agent: str) -> None:
    if agent in SUPPORTED_AGENTS:
        return
    raise ValueError(f"Unsupported LLM agent: {agent!r}. Use codex, claude, or gemini.")
