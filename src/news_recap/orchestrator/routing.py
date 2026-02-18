"""Routing resolution helpers for per-task LLM execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from news_recap.config import OrchestratorSettings
from news_recap.ingestion.storage.common import utc_now
from news_recap.orchestrator.contracts import TaskInputContract

SUPPORTED_AGENTS = ("claude", "codex", "gemini")
SUPPORTED_PROFILES = ("fast", "quality")
ROUTING_SCHEMA_VERSION = 1


@dataclass(slots=True)
class FrozenRouting:
    """Resolved immutable routing payload stored in task metadata."""

    schema_version: int
    agent: str
    profile: str
    model: str
    command_template: str
    resolved_at: str
    resolved_by: str

    def to_metadata(self) -> dict[str, object]:
        """Serialize frozen routing for task_input metadata."""

        return {
            "schema_version": self.schema_version,
            "agent": self.agent,
            "profile": self.profile,
            "model": self.model,
            "command_template": self.command_template,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }


@dataclass(slots=True)
class RoutingDefaults:
    """Settings snapshot used for enqueue-time routing and legacy fallback."""

    default_agent: str
    task_type_profile_map: dict[str, str]
    command_templates: dict[str, str]
    models: dict[str, dict[str, str]]

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
        models = {
            "claude": {
                "fast": settings.claude_model_fast,
                "quality": settings.claude_model_quality,
            },
            "codex": {
                "fast": settings.codex_model_fast,
                "quality": settings.codex_model_quality,
            },
            "gemini": {
                "fast": settings.gemini_model_fast,
                "quality": settings.gemini_model_quality,
            },
        }
        for agent, profile_models in models.items():
            for profile, model in profile_models.items():
                if profile not in SUPPORTED_PROFILES:
                    raise ValueError(f"Unsupported profile={profile!r} for agent={agent!r}")
                if not model.strip():
                    raise ValueError(
                        f"Empty model id for agent={agent!r}, profile={profile!r}",
                    )
        return cls(
            default_agent=default_agent,
            task_type_profile_map={
                task_type.lower(): profile.lower()
                for task_type, profile in settings.task_type_profile_map.items()
            },
            command_templates=command_templates,
            models=models,
        )


def resolve_routing_for_enqueue(  # noqa: PLR0913
    *,
    defaults: RoutingDefaults,
    task_type: str,
    agent_override: str | None,
    profile_override: str | None,
    model_override: str | None,
) -> FrozenRouting:
    """Resolve and freeze routing at enqueue time."""

    agent = (
        _normalize_agent(agent_override) if agent_override is not None else defaults.default_agent
    )
    _validate_supported_agent(agent)
    profile = (
        _normalize_profile(profile_override)
        if profile_override is not None
        else defaults.task_type_profile_map.get(task_type.strip().lower(), "fast")
    )
    _validate_supported_profile(profile)
    model = (
        model_override.strip() if model_override is not None else defaults.models[agent][profile]
    )
    if not model:
        raise ValueError(
            f"Resolved model is empty for agent={agent!r}, profile={profile!r}",
        )
    command_template = defaults.command_templates[agent].strip()
    if not command_template:
        raise ValueError(f"Resolved command template is empty for agent={agent!r}")
    return FrozenRouting(
        schema_version=ROUTING_SCHEMA_VERSION,
        agent=agent,
        profile=profile,
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
        profile_override=None,
        model_override=None,
    )
    return (
        FrozenRouting(
            schema_version=fallback.schema_version,
            agent=fallback.agent,
            profile=fallback.profile,
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
    profile = raw.get("profile")
    model = raw.get("model")
    command_template = raw.get("command_template")
    resolved_at = raw.get("resolved_at")
    resolved_by = raw.get("resolved_by")

    if schema_version != ROUTING_SCHEMA_VERSION:
        return None
    if not isinstance(agent, str) or not agent.strip():
        return None
    agent = _normalize_agent(agent)
    if agent not in SUPPORTED_AGENTS:
        return None
    if not isinstance(profile, str) or not profile.strip():
        return None
    profile = _normalize_profile(profile)
    if profile not in SUPPORTED_PROFILES:
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
        profile=profile,
        model=model.strip(),
        command_template=command_template.strip(),
        resolved_at=resolved_at.strip(),
        resolved_by=resolved_by.strip(),
    )


def _normalize_agent(value: str) -> str:
    return value.strip().lower()


def _normalize_profile(value: str) -> str:
    return value.strip().lower()


def _validate_supported_agent(agent: str) -> None:
    if agent in SUPPORTED_AGENTS:
        return
    raise ValueError(f"Unsupported LLM agent: {agent!r}. Use codex, claude, or gemini.")


def _validate_supported_profile(profile: str) -> None:
    if profile not in SUPPORTED_PROFILES:
        raise ValueError(
            f"Unsupported model profile: {profile!r}. Use one of {SUPPORTED_PROFILES}.",
        )
