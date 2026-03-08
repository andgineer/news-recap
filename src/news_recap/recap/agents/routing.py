"""Routing resolution helpers for per-task LLM execution."""

from __future__ import annotations

from typing import Any

import msgspec

from news_recap.config import OrchestratorSettings
from news_recap.recap.contracts import TaskInputContract
from news_recap.storage.io import utc_now

SUPPORTED_AGENTS = ("claude", "codex", "gemini")
ROUTING_SCHEMA_VERSION = 3


class FrozenRouting(msgspec.Struct):
    """Resolved immutable routing payload stored in task metadata."""

    schema_version: int
    agent: str
    model: str
    command_template: str
    resolved_at: str
    resolved_by: str
    execution_backend: str = "cli"

    def to_metadata(self) -> dict[str, object]:
        return msgspec.structs.asdict(self)


class RoutingDefaults(msgspec.Struct):
    """Settings snapshot used for enqueue-time routing."""

    default_agent: str
    task_model_map: dict[str, dict[str, str]]
    task_type_timeout_map: dict[str, int]
    command_templates: dict[str, str]
    agent_max_parallel: dict[str, int] = msgspec.field(default_factory=dict)
    agent_launch_delay: dict[str, float] = msgspec.field(default_factory=dict)
    execution_backend: str = "cli"
    api_model_map: dict[str, str] = msgspec.field(default_factory=dict)
    api_max_parallel: int = 5
    api_concurrency_recovery_successes: int = 10
    api_downshift_pause_seconds: float = 2.0
    api_retry_max_backoff_seconds: float = 60.0
    api_retry_jitter_seconds: float = 5.0

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
        execution_backend = settings.execution_backend
        command_templates = {
            "claude": settings.claude_command_template,
            "codex": settings.codex_command_template,
            "gemini": settings.gemini_command_template,
        }
        if execution_backend == "cli":
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
            execution_backend=execution_backend,
            api_model_map=dict(settings.api_model_map),
            api_max_parallel=settings.api_max_parallel,
            api_concurrency_recovery_successes=settings.api_concurrency_recovery_successes,
            api_downshift_pause_seconds=settings.api_downshift_pause_seconds,
            api_retry_max_backoff_seconds=settings.api_retry_max_backoff_seconds,
            api_retry_jitter_seconds=settings.api_retry_jitter_seconds,
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

    execution_backend = defaults.execution_backend

    if execution_backend == "api":
        if agent != "claude":
            raise ValueError(
                f"execution_backend=api requires agent=claude; got agent={agent}.\n"
                "Pass --agent claude or set NEWS_RECAP_LLM_DEFAULT_AGENT=claude.",
            )
        model = (
            model_override.strip()
            if model_override is not None
            else defaults.api_model_map.get(task_type.strip().lower(), "")
        )
        if not model:
            raise ValueError(
                f"No API model configured for task_type={task_type!r}. "
                "Add it to api_model_map or set NEWS_RECAP_API_MODEL_MAP.",
            )
        command_template = ""
    else:
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
        execution_backend=execution_backend,
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
            execution_backend=fallback.execution_backend,
            resolved_at=utc_now().isoformat(),
            resolved_by="worker_fallback",
        ),
        reason,
    )


def _parse_frozen_routing(raw: dict[str, Any]) -> FrozenRouting | None:  # noqa: C901, PLR0911, PLR0912
    schema_version = raw.get("schema_version")
    agent = raw.get("agent")
    model = raw.get("model")
    command_template = raw.get("command_template")
    resolved_at = raw.get("resolved_at")
    resolved_by = raw.get("resolved_by")

    # Accept versions 1, 2 (pre-execution_backend), 3 (current). Reject others.
    if schema_version not in (1, 2, ROUTING_SCHEMA_VERSION):
        return None
    if not isinstance(agent, str) or not agent.strip():
        return None
    agent = _normalize_agent(agent)
    if agent not in SUPPORTED_AGENTS:
        return None
    if not isinstance(model, str) or not model.strip():
        return None
    if not isinstance(resolved_at, str) or not resolved_at.strip():
        return None
    if not isinstance(resolved_by, str) or not resolved_by.strip():
        return None

    # Determine execution_backend: defaults to "cli" for v1/v2; read from dict for v3.
    if schema_version == ROUTING_SCHEMA_VERSION:
        execution_backend = raw.get("execution_backend", "cli")
        if execution_backend not in ("cli", "api"):
            return None
    else:
        execution_backend = "cli"

    # command_template must be non-empty for cli, must be "" for api.
    if not isinstance(command_template, str):
        return None
    if execution_backend == "api":
        if command_template != "":
            return None
    elif not command_template.strip():
        return None

    return FrozenRouting(
        schema_version=ROUTING_SCHEMA_VERSION,
        agent=agent,
        model=model.strip(),
        command_template=command_template
        if execution_backend == "api"
        else command_template.strip(),
        execution_backend=execution_backend,
        resolved_at=resolved_at.strip(),
        resolved_by=resolved_by.strip(),
    )


def _normalize_agent(value: str) -> str:
    return value.strip().lower()


def _validate_supported_agent(agent: str) -> None:
    if agent in SUPPORTED_AGENTS:
        return
    raise ValueError(f"Unsupported LLM agent: {agent!r}. Use codex, claude, or gemini.")
