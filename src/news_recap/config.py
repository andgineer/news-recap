"""Runtime configuration for ingestion and recap pipeline."""

from __future__ import annotations

import logging
import os
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import msgspec
from dotenv import dotenv_values

from news_recap.config_file import (
    AGENTS,
    STEP_BACKENDS,
    ConfigError,
    config_path,
    load_config_file,
)
from news_recap.recap.models import UserPreferences

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionSettings:
    """Generic ingestion-stage settings."""

    page_size: int = 50
    max_pages: int = 0
    backfill_max_gaps: int = 10
    clean_text_max_chars: int = 12_000
    gc_retention_days: int = 7
    digest_lookback_days: int = 2
    min_resource_chars: int = 200


@dataclass(slots=True)
class DedupSettings:
    """Embedding-based dedup settings for the recap pipeline."""

    threshold: float = 0.90
    model_name: str = "intfloat/multilingual-e5-small"


TYPESAFE_API_KEY_VAR = "TYPESAFE_API_KEY"
DEFAULT_JEV_MODEL = "jev-1.13.0"
DEFAULT_AGENT = "antigravity"
DATA_DIR_VAR = "NEWS_RECAP_DATA_DIR"


@dataclass(slots=True)
class JevSettings:
    """TypeSafe Jev settings: API key and which pipeline steps use Jev."""

    api_key: str | None = field(default=None, repr=False)
    model: str = DEFAULT_JEV_MODEL
    classify_backend: str = "llm"
    dedup_backend: str = "llm"


@dataclass(slots=True)
class RssSettings:
    """RSS source settings."""

    feed_urls: tuple[str, ...] = ()
    default_items_per_feed: int = 10_000
    per_feed_items: dict[str, int] = field(default_factory=dict)
    snapshot_max_age_hours: int = 24
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    request_timeout_seconds: float = 30.0


_DEFAULT_AGENT_API_KEY_VARS: dict[str, list[str]] = {
    "claude": ["ANTHROPIC_API_KEY"],
    "codex": ["OPENAI_API_KEY"],
    "antigravity": ["ANTIGRAVITY_API_KEY"],
}

_DEFAULT_CODEX_CMD = (
    "codex exec --sandbox workspace-write "
    "-c sandbox_workspace_write.network_access=true "
    '{model} "Read your task from {prompt_file} and execute it."'
)
_DEFAULT_CLAUDE_CMD = (
    "claude -p {model} --permission-mode dontAsk "
    '--allowed-tools "Read,WebFetch,'
    'Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" '
    '-- "Read your task from {prompt_file} and execute it."'
)
_DEFAULT_ANTIGRAVITY_CMD = (
    "agy {model} --dangerously-skip-permissions --output-format json "
    '-p "Read your task from {prompt_file} and execute it."'
)


def _default_agent_max_parallel() -> dict[str, int]:
    # antigravity: 1 — free tier shares a low RPM/capacity pool across all
    # sessions; concurrent agents reliably trigger 429s.
    return {"codex": 3, "claude": 2, "antigravity": 1}


_NO_THINKING = {"MAX_THINKING_TOKENS": "0"}
_MAX_OUTPUT = {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}
# Caps the hidden thinking scratchpad to a fixed token budget.
# Do NOT add CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING here — that flag disables the
# hidden scratchpad and forces the model to write its reasoning into stdout,
# which contaminates the structured output the parser expects.
_CAPPED_THINKING = {"CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1", "MAX_THINKING_TOKENS": "4000"}
_CODEX_LUNA_FLAGS = "--model gpt-5.6-luna -c model_reasoning_effort=low"
_CODEX_TERRA_FLAGS = "--model gpt-5.6-terra -c model_reasoning_effort=low"
_CODEX_SOL_FLAGS = "--model gpt-5.6-sol -c model_reasoning_effort=low"
_CLAUDE_HAIKU_FLAGS = "--model haiku"
_CLAUDE_SONNET_FLAGS = "--model claude-sonnet-5 --effort low"
_ANTIGRAVITY_FLASH_LOW_FLAGS = "--model gemini-3.7-flash --effort low"


def _default_task_model_map() -> dict[str, dict[str, Any]]:
    return {
        "recap_classify": {
            "codex": {"model": _CODEX_LUNA_FLAGS},
            "claude": {"model": _CLAUDE_HAIKU_FLAGS, "env": _NO_THINKING},
            "antigravity": {"model": _ANTIGRAVITY_FLASH_LOW_FLAGS},
        },
        "recap_enrich": {
            "codex": {"model": _CODEX_TERRA_FLAGS},
            "claude": {"model": _CLAUDE_HAIKU_FLAGS, "env": _NO_THINKING},
            "antigravity": {"model": _ANTIGRAVITY_FLASH_LOW_FLAGS},
        },
        "recap_dedup": {
            "codex": {"model": _CODEX_TERRA_FLAGS},
            "claude": {"model": _CLAUDE_HAIKU_FLAGS, "env": _NO_THINKING},
            "antigravity": {"model": _ANTIGRAVITY_FLASH_LOW_FLAGS},
        },
        "recap_oneshot_digest": {
            "codex": {"model": _CODEX_TERRA_FLAGS},
            "claude": {"model": _CLAUDE_HAIKU_FLAGS, "env": _MAX_OUTPUT},
            "antigravity": {"model": _ANTIGRAVITY_FLASH_LOW_FLAGS},
        },
        "recap_merge_sections": {
            "codex": {"model": _CODEX_SOL_FLAGS},
            "claude": {"model": _CLAUDE_SONNET_FLAGS},
            "antigravity": {"model": _ANTIGRAVITY_FLASH_LOW_FLAGS},
        },
        "recap_refine_layout": {
            "codex": {"model": _CODEX_LUNA_FLAGS},
            "claude": {"model": _CLAUDE_HAIKU_FLAGS},
            "antigravity": {"model": _ANTIGRAVITY_FLASH_LOW_FLAGS},
        },
    }


def _default_api_model_map() -> dict[str, str]:
    return {
        "recap_classify": "claude-haiku-4-5-20251001",
        "recap_enrich": "claude-haiku-4-5-20251001",
        "recap_dedup": "claude-haiku-4-5-20251001",
        "recap_oneshot_digest": "claude-haiku-4-5-20251001",
        "recap_merge_sections": "claude-sonnet-5",
        "recap_refine_layout": "claude-haiku-4-5-20251001",
    }


@dataclass(slots=True)
class OrchestratorSettings:
    """CLI orchestrator settings."""

    workdir_root: Path = Path.home() / ".news_recap_data" / "workdir"
    default_agent: str = DEFAULT_AGENT
    execution_backend: str = "cli"
    task_model_map: dict[str, dict[str, Any]] = field(
        default_factory=_default_task_model_map,
    )
    api_model_map: dict[str, str] = field(
        default_factory=_default_api_model_map,
    )
    task_type_timeout_map: dict[str, int] = field(
        default_factory=lambda: {
            "recap_classify": 900,
            "recap_enrich": 600,
            "recap_dedup": 600,
            "recap_oneshot_digest": 1200,
            "recap_refine_layout": 600,
        },
    )
    agent_max_parallel: dict[str, int] = field(
        default_factory=_default_agent_max_parallel,
    )
    agent_launch_delay: dict[str, float] = field(
        default_factory=lambda: {"antigravity": 10.0, "claude": 3.0, "codex": 3.0},
    )
    codex_command_template: str = _DEFAULT_CODEX_CMD
    claude_command_template: str = _DEFAULT_CLAUDE_CMD
    antigravity_command_template: str = _DEFAULT_ANTIGRAVITY_CMD
    agent_api_key_vars: dict[str, list[str]] = field(
        default_factory=lambda: dict(_DEFAULT_AGENT_API_KEY_VARS),
    )
    api_max_parallel: int = 5
    api_concurrency_recovery_successes: int = 10
    api_retry_max_backoff_seconds: float = 60.0
    api_retry_jitter_seconds: float = 5.0
    api_downshift_pause_seconds: float = 2.0


@dataclass(slots=True)
class Settings:
    """Application settings grouped by domain concerns."""

    data_dir: Path = Path.home() / ".news_recap_data"
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    rss: RssSettings = field(default_factory=RssSettings)
    orchestrator: OrchestratorSettings = field(default_factory=OrchestratorSettings)
    jev: JevSettings = field(default_factory=JevSettings)
    preferences: UserPreferences = field(default_factory=UserPreferences)

    @classmethod
    def defaults(cls, data_dir: Path) -> Settings:
        """Release defaults for *data_dir*, before ``config.toml`` is applied."""
        return cls(
            data_dir=data_dir,
            orchestrator=OrchestratorSettings(workdir_root=data_dir / "workdir"),
        )

    @classmethod
    def load(cls, execution_backend: str | None = None) -> Settings:
        """Release defaults overridden by ``<data_dir>/config.toml``.

        *execution_backend* overrides the file's ``llm.execution_backend``; ``"api"`` also
        forces the agent to ``claude``, the only provider of the API backend.
        """
        data_dir = data_dir_from_env()
        settings = cls.defaults(data_dir)
        for key, value in load_config_file(config_path(data_dir)):
            _apply(settings, key.target, value)
        settings.jev.api_key = resolve_typesafe_api_key(data_dir)
        for step in ("classify", "dedup"):
            _require_jev_key(settings, step)
        if execution_backend is not None:
            settings.orchestrator.execution_backend = execution_backend
            if execution_backend == "api":
                settings.orchestrator.default_agent = "claude"
        try:
            settings.validate()
        except ValueError as error:
            raise ConfigError(f"{config_path(data_dir)}: {error}") from error
        return settings

    def validate(self) -> None:
        """Validate cross-domain runtime settings and fail fast on invalid config."""

        self._validate_storage_and_ingestion()
        self._validate_orchestrator_routing()
        self._validate_orchestrator_runtime_limits()

    def _validate_storage_and_ingestion(self) -> None:
        if self.ingestion.gc_retention_days < 1:
            raise ValueError("ingestion.retention_days must be >= 1.")
        if self.ingestion.digest_lookback_days < 1:
            raise ValueError("ingestion.lookback_days must be >= 1.")
        if not (0.0 < self.dedup.threshold <= 1.0):
            raise ValueError("dedup.threshold must be in (0, 1].")
        if self.jev.classify_backend not in STEP_BACKENDS:
            raise ValueError("classify_backend must be 'llm' or 'jev'.")
        if self.jev.dedup_backend not in STEP_BACKENDS:
            raise ValueError("dedup_backend must be 'llm' or 'jev'.")

    def _validate_orchestrator_routing(self) -> None:  # noqa: C901
        supported_agents = set(AGENTS)
        default_agent = self.orchestrator.default_agent.strip().lower()
        if default_agent not in supported_agents:
            raise ValueError(f"agent must be one of: {', '.join(AGENTS)}.")

        execution_backend = self.orchestrator.execution_backend
        if execution_backend not in {"cli", "api"}:
            raise ValueError("llm.execution_backend must be 'cli' or 'api'.")
        if execution_backend == "api" and default_agent != "claude":
            raise ValueError(
                f"execution_backend=api requires the claude agent.\n"
                f'Set agent = "claude" in config.toml (current value: {default_agent}).',
            )

        for task_type, agent_models in self.orchestrator.task_model_map.items():
            if not task_type.strip():
                raise ValueError("task_model_map contains empty task_type key.")
            for agent, entry in agent_models.items():
                if agent not in supported_agents:
                    raise ValueError(
                        f"task_model_map[{task_type!r}] has unsupported agent: {agent!r}",
                    )
                model = entry.get("model", "") if isinstance(entry, dict) else entry
                if not model or not model.strip():
                    raise ValueError(
                        f"task_model_map[{task_type!r}][{agent!r}] model must not be empty.",
                    )

        if execution_backend == "cli":
            for name, template in (
                ("codex_command_template", self.orchestrator.codex_command_template),
                ("claude_command_template", self.orchestrator.claude_command_template),
                ("antigravity_command_template", self.orchestrator.antigravity_command_template),
            ):
                _validate_command_template(name=name, template=template)

    def _validate_orchestrator_runtime_limits(self) -> None:
        o = self.orchestrator
        if o.api_max_parallel < 1:
            raise ValueError("api.max_parallel must be >= 1.")
        if o.api_concurrency_recovery_successes < 1:
            raise ValueError("api.concurrency_recovery_successes must be >= 1.")
        if o.api_retry_max_backoff_seconds < 0:
            raise ValueError("api.retry_max_backoff_seconds must be >= 0.")
        if o.api_retry_jitter_seconds < 0:
            raise ValueError("api.retry_jitter_seconds must be >= 0.")
        if o.api_downshift_pause_seconds < 0:
            raise ValueError("api.downshift_pause_seconds must be >= 0.")

    def validate_for_rss(self, override_feed_urls: tuple[str, ...] = ()) -> None:
        """Raise configuration error if RSS feed URLs are missing or invalid."""

        effective_feed_urls = _normalize_feed_urls(override_feed_urls or self.rss.feed_urls)
        if not effective_feed_urls:
            raise ValueError(
                "At least one RSS feed URL is required. "
                "Run `news-recap config set rss URL` or pass --rss.",
            )

        for feed_url in effective_feed_urls:
            _validate_feed_url(feed_url)
        if self.rss.default_items_per_feed <= 0:
            raise ValueError("rss.default_items_per_feed must be a positive integer.")
        for feed_url, items in self.rss.per_feed_items.items():
            _validate_feed_url(feed_url)
            if items <= 0:
                raise ValueError(
                    f"Per-feed RSS items override must be positive: {feed_url!r} -> {items}",
                )
        if self.rss.snapshot_max_age_hours < 0:
            raise ValueError("rss.snapshot_max_age_hours must be >= 0.")


def data_dir_from_env() -> Path:
    """The data directory: ``NEWS_RECAP_DATA_DIR`` or ``~/.news_recap_data``."""
    return Path(os.getenv(DATA_DIR_VAR) or Path.home() / ".news_recap_data")


def resolve_typesafe_api_key(data_dir: Path) -> str | None:
    """Return the TypeSafe API key: env var, then ``./.env``, then ``<data_dir>/.env``.

    ``.env`` values are never exported to ``os.environ``, so agent subprocesses
    cannot inherit them.
    """
    value = os.getenv(TYPESAFE_API_KEY_VAR, "").strip()
    if value:
        return value
    for env_file in (Path.cwd() / ".env", data_dir / ".env"):
        if env_file.is_file():
            value = (dotenv_values(env_file).get(TYPESAFE_API_KEY_VAR) or "").strip()
            if value:
                return value
    return None


def _require_jev_key(settings: Settings, step: str) -> None:
    attr = f"{step}_backend"
    if getattr(settings.jev, attr) == "jev" and settings.jev.api_key is None:
        logger.warning(
            '%s = "jev" in config.toml but %s is not set (env, ./.env, %s); %s uses the LLM.',
            attr,
            TYPESAFE_API_KEY_VAR,
            settings.data_dir / ".env",
            step,
        )
        setattr(settings.jev, attr, "llm")


def _apply(settings: Settings, target: str, value: Any) -> None:
    """Set the ``Settings`` attribute at dotted *target* from a validated file value."""
    *path, attr = target.split(".")
    obj: Any = settings
    for part in path:
        obj = getattr(obj, part)
    if target.startswith("preferences."):
        settings.preferences = msgspec.structs.replace(
            settings.preferences,
            **{attr: value.strip()},
        )
        return
    if target == "rss.feed_urls":
        value = _normalize_feed_urls(value)
    elif target == "orchestrator.workdir_root":
        value = Path(value).expanduser()
    elif target == "orchestrator.task_model_map":
        value = _merge_task_model_map(obj.task_model_map, value)
    elif target == "orchestrator.api_model_map":
        value = {**obj.api_model_map, **{str(k).lower(): str(v) for k, v in value.items()}}
    setattr(obj, attr, value)


def _merge_task_model_map(
    defaults: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Override the model flags of single task/agent entries, keeping each entry's env."""
    merged = {
        task: {agent: dict(e) for agent, e in agents.items()} for task, agents in defaults.items()
    }
    for task, agents in overrides.items():
        for agent, flags in agents.items():
            entry = merged.setdefault(task.lower(), {}).setdefault(agent.lower(), {})
            entry["model"] = flags.strip()
    return merged


def _normalize_feed_urls(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def _validate_feed_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "Invalid RSS feed URL: "
            f"{value!r}. Expected an absolute URL with http:// or https:// scheme.",
        )


def _validate_command_template(*, name: str, template: str) -> None:
    stripped = template.strip()
    if not stripped:
        raise ValueError(f"{name} must not be empty.")

    formatter = string.Formatter()
    allowed = {"model", "prompt_file"}
    seen_fields: set[str] = set()

    for _, field_name, _, _ in formatter.parse(stripped):
        if field_name is None:
            continue
        if field_name not in allowed:
            raise ValueError(
                f"{name} uses unsupported placeholder {{{field_name}}}. "
                f"Allowed: {', '.join(sorted(allowed))}",
            )
        seen_fields.add(field_name)

    if "prompt_file" not in seen_fields:
        raise ValueError(f"{name} must include required placeholder {{prompt_file}}.")

    rendered = stripped.format(
        model="model-id",
        prompt_file="prompt.txt",
    ).strip()
    if not rendered:
        raise ValueError(f"{name} rendered an empty command.")
