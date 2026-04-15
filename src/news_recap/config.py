"""Runtime configuration for ingestion and recap pipeline."""

from __future__ import annotations

import logging
import os
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
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
_DEFAULT_GEMINI_CMD = (
    "gemini {model} --approval-mode auto_edit "
    '--prompt "Read your task from {prompt_file} and execute it."'
)


@dataclass(slots=True)
class OrchestratorSettings:
    """CLI orchestrator settings."""

    workdir_root: Path = Path.home() / ".news_recap_data" / "workdir"
    default_agent: str = "codex"
    execution_backend: str = "cli"
    task_model_map: dict[str, dict[str, Any]] = field(
        default_factory=lambda: _default_task_model_map(),
    )
    api_model_map: dict[str, str] = field(
        default_factory=lambda: _default_api_model_map(),
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
        default_factory=lambda: _default_agent_max_parallel(),
    )
    agent_launch_delay: dict[str, float] = field(
        default_factory=lambda: {"gemini": 3.0, "claude": 3.0, "codex": 3.0},
    )
    codex_command_template: str = _DEFAULT_CODEX_CMD
    claude_command_template: str = _DEFAULT_CLAUDE_CMD
    gemini_command_template: str = _DEFAULT_GEMINI_CMD
    agent_api_key_vars: dict[str, list[str]] = field(
        default_factory=lambda: dict(_DEFAULT_AGENT_API_KEY_VARS),
    )
    worker_id: str = "worker-default"
    poll_interval_seconds: float = 2.0
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    worker_stale_attempt_seconds: int = 1_800
    worker_graceful_shutdown_seconds: int = 30
    api_max_parallel: int = 5
    api_timeout_seconds: int = 120
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

    @classmethod
    def from_env(
        cls,
        execution_backend: str | None = None,
    ) -> Settings:
        """Load settings from environment with sane defaults for local development.

        *execution_backend* overrides ``NEWS_RECAP_EXECUTION_BACKEND`` when provided.
        Passing ``"api"`` also forces ``default_agent`` to ``"claude"`` (the only
        supported provider for the API backend).
        """

        rss_urls = _collect_feed_urls()
        default_data_dir = str(Path.home() / ".news_recap_data")
        data_dir = Path(os.getenv("NEWS_RECAP_DATA_DIR", default_data_dir))
        workdir_env = os.getenv("NEWS_RECAP_LLM_WORKDIR_ROOT")
        workdir_root = Path(workdir_env) if workdir_env else data_dir / "workdir"

        env_agent = os.getenv("NEWS_RECAP_LLM_DEFAULT_AGENT")
        if env_agent:
            default_agent = env_agent
        else:
            from news_recap.user_config import DEFAULT_AGENT, UserConfigManager

            default_agent = UserConfigManager(data_dir).load().get("default_agent", DEFAULT_AGENT)

        settings = cls(
            data_dir=data_dir,
            ingestion=IngestionSettings(
                page_size=int(
                    os.getenv(
                        "NEWS_RECAP_INGESTION_PAGE_SIZE",
                        os.getenv("NEWS_RECAP_INOREADER_PAGE_SIZE", "50"),
                    ),
                ),
                max_pages=int(
                    os.getenv(
                        "NEWS_RECAP_INGESTION_MAX_PAGES",
                        os.getenv("NEWS_RECAP_INOREADER_MAX_PAGES", "0"),
                    ),
                ),
                backfill_max_gaps=int(os.getenv("NEWS_RECAP_BACKFILL_MAX_GAPS", "10")),
                clean_text_max_chars=int(os.getenv("NEWS_RECAP_CLEAN_TEXT_MAX_CHARS", "12000")),
                gc_retention_days=int(os.getenv("NEWS_RECAP_GC_RETENTION_DAYS", "7")),
                digest_lookback_days=int(os.getenv("NEWS_RECAP_DIGEST_LOOKBACK_DAYS", "2")),
                min_resource_chars=int(os.getenv("NEWS_RECAP_MIN_RESOURCE_CHARS", "200")),
            ),
            dedup=DedupSettings(
                threshold=float(os.getenv("NEWS_RECAP_DEDUP_THRESHOLD", "0.90")),
                model_name=os.getenv(
                    "NEWS_RECAP_DEDUP_MODEL_NAME",
                    "intfloat/multilingual-e5-small",
                ),
            ),
            rss=RssSettings(
                feed_urls=rss_urls,
                default_items_per_feed=int(
                    os.getenv("NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED", "10000"),
                ),
                per_feed_items=_collect_feed_item_overrides(),
                snapshot_max_age_hours=int(
                    os.getenv("NEWS_RECAP_RSS_SNAPSHOT_MAX_AGE_HOURS", "24"),
                ),
                max_retries=int(os.getenv("NEWS_RECAP_RSS_MAX_RETRIES", "3")),
                retry_backoff_seconds=float(
                    os.getenv("NEWS_RECAP_RSS_RETRY_BACKOFF_SECONDS", "1.0"),
                ),
                request_timeout_seconds=float(
                    os.getenv("NEWS_RECAP_RSS_REQUEST_TIMEOUT_SECONDS", "30.0"),
                ),
            ),
            orchestrator=OrchestratorSettings(
                workdir_root=workdir_root,
                default_agent=default_agent,
                execution_backend=os.getenv("NEWS_RECAP_EXECUTION_BACKEND", "cli").strip(),
                codex_command_template=_DEFAULT_CODEX_CMD,
                claude_command_template=_DEFAULT_CLAUDE_CMD,
                gemini_command_template=_DEFAULT_GEMINI_CMD,
                task_model_map=_collect_task_model_map(),
                api_model_map=_collect_api_model_map(),
                agent_max_parallel=_default_agent_max_parallel(),
                worker_id=os.getenv("NEWS_RECAP_LLM_WORKER_ID", "worker-default"),
                poll_interval_seconds=float(
                    os.getenv("NEWS_RECAP_LLM_POLL_INTERVAL_SECONDS", "2.0"),
                ),
                retry_base_seconds=int(
                    os.getenv("NEWS_RECAP_LLM_RETRY_BASE_SECONDS", "30"),
                ),
                retry_max_seconds=int(
                    os.getenv("NEWS_RECAP_LLM_RETRY_MAX_SECONDS", "900"),
                ),
                worker_stale_attempt_seconds=int(
                    os.getenv("NEWS_RECAP_WORKER_STALE_ATTEMPT_SECONDS", "1800"),
                ),
                worker_graceful_shutdown_seconds=int(
                    os.getenv("NEWS_RECAP_WORKER_GRACEFUL_SHUTDOWN_SECONDS", "30"),
                ),
                api_max_parallel=int(os.getenv("NEWS_RECAP_API_MAX_PARALLEL", "5")),
                api_timeout_seconds=int(os.getenv("NEWS_RECAP_API_TIMEOUT_SECONDS", "120")),
                api_concurrency_recovery_successes=int(
                    os.getenv("NEWS_RECAP_API_CONCURRENCY_RECOVERY_SUCCESSES", "10"),
                ),
                api_retry_max_backoff_seconds=float(
                    os.getenv("NEWS_RECAP_API_RETRY_MAX_BACKOFF_SECONDS", "60.0"),
                ),
                api_retry_jitter_seconds=float(
                    os.getenv("NEWS_RECAP_API_RETRY_JITTER_SECONDS", "5.0"),
                ),
                api_downshift_pause_seconds=float(
                    os.getenv("NEWS_RECAP_API_DOWNSHIFT_PAUSE_SECONDS", "2.0"),
                ),
            ),
        )
        if execution_backend is not None:
            settings.orchestrator.execution_backend = execution_backend
            if execution_backend == "api":
                settings.orchestrator.default_agent = "claude"
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate cross-domain runtime settings and fail fast on invalid config."""

        self._validate_storage_and_ingestion()
        self._validate_orchestrator_routing()
        self._validate_orchestrator_runtime_limits()

    def _validate_storage_and_ingestion(self) -> None:
        if self.ingestion.gc_retention_days < 1:
            raise ValueError("NEWS_RECAP_GC_RETENTION_DAYS must be >= 1.")
        if self.ingestion.digest_lookback_days < 1:
            raise ValueError("NEWS_RECAP_DIGEST_LOOKBACK_DAYS must be >= 1.")
        if not (0.0 < self.dedup.threshold <= 1.0):
            raise ValueError("NEWS_RECAP_DEDUP_THRESHOLD must be in (0, 1].")

    def _validate_orchestrator_routing(self) -> None:  # noqa: C901
        supported_agents = {"codex", "claude", "gemini"}
        default_agent = self.orchestrator.default_agent.strip().lower()
        if default_agent not in supported_agents:
            raise ValueError(
                "NEWS_RECAP_LLM_DEFAULT_AGENT must be one of: codex, claude, gemini.",
            )

        execution_backend = self.orchestrator.execution_backend
        if execution_backend not in {"cli", "api"}:
            raise ValueError("NEWS_RECAP_EXECUTION_BACKEND must be 'cli' or 'api'.")
        if execution_backend == "api" and default_agent != "claude":
            raise ValueError(
                f"execution_backend=api requires default_agent=claude.\n"
                f"Set NEWS_RECAP_LLM_DEFAULT_AGENT=claude (current value: {default_agent}).",
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
                ("gemini_command_template", self.orchestrator.gemini_command_template),
            ):
                _validate_command_template(name=name, template=template)

    def _validate_orchestrator_runtime_limits(self) -> None:
        if not self.orchestrator.worker_id.strip():
            raise ValueError("NEWS_RECAP_LLM_WORKER_ID must not be empty.")
        self._validate_retry_limits()
        self._validate_api_limits()

    def _validate_retry_limits(self) -> None:
        o = self.orchestrator
        if o.poll_interval_seconds < 0:
            raise ValueError("NEWS_RECAP_LLM_POLL_INTERVAL_SECONDS must be >= 0.")
        if o.retry_base_seconds < 0:
            raise ValueError("NEWS_RECAP_LLM_RETRY_BASE_SECONDS must be >= 0.")
        if o.retry_max_seconds < 0:
            raise ValueError("NEWS_RECAP_LLM_RETRY_MAX_SECONDS must be >= 0.")
        if o.retry_max_seconds < o.retry_base_seconds:
            raise ValueError(
                "NEWS_RECAP_LLM_RETRY_MAX_SECONDS must be >= NEWS_RECAP_LLM_RETRY_BASE_SECONDS.",
            )
        if o.worker_stale_attempt_seconds <= 0:
            raise ValueError("NEWS_RECAP_WORKER_STALE_ATTEMPT_SECONDS must be > 0.")
        if o.worker_graceful_shutdown_seconds <= 0:
            raise ValueError("NEWS_RECAP_WORKER_GRACEFUL_SHUTDOWN_SECONDS must be > 0.")

    def _validate_api_limits(self) -> None:
        o = self.orchestrator
        if o.api_max_parallel < 1:
            raise ValueError("NEWS_RECAP_API_MAX_PARALLEL must be >= 1.")
        if o.api_timeout_seconds <= 0:
            raise ValueError("NEWS_RECAP_API_TIMEOUT_SECONDS must be > 0.")
        if o.api_concurrency_recovery_successes < 1:
            raise ValueError("NEWS_RECAP_API_CONCURRENCY_RECOVERY_SUCCESSES must be >= 1.")
        if o.api_retry_max_backoff_seconds < 0:
            raise ValueError("NEWS_RECAP_API_RETRY_MAX_BACKOFF_SECONDS must be >= 0.")
        if o.api_retry_jitter_seconds < 0:
            raise ValueError("NEWS_RECAP_API_RETRY_JITTER_SECONDS must be >= 0.")
        if o.api_downshift_pause_seconds < 0:
            raise ValueError("NEWS_RECAP_API_DOWNSHIFT_PAUSE_SECONDS must be >= 0.")

    def validate_for_rss(self, override_feed_urls: tuple[str, ...] = ()) -> None:
        """Raise configuration error if RSS feed URLs are missing or invalid."""

        effective_feed_urls = _normalize_feed_urls(override_feed_urls or self.rss.feed_urls)
        if not effective_feed_urls:
            raise ValueError(
                "At least one RSS feed URL is required. "
                "Set NEWS_RECAP_RSS_FEED_URLS or pass --rss.",
            )

        for feed_url in effective_feed_urls:
            _validate_feed_url(feed_url)
        if self.rss.default_items_per_feed <= 0:
            raise ValueError(
                "NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED must be a positive integer.",
            )
        for feed_url, items in self.rss.per_feed_items.items():
            _validate_feed_url(feed_url)
            if items <= 0:
                raise ValueError(
                    f"Per-feed RSS items override must be positive: {feed_url!r} -> {items}",
                )
        if self.rss.snapshot_max_age_hours < 0:
            raise ValueError("NEWS_RECAP_RSS_SNAPSHOT_MAX_AGE_HOURS must be >= 0.")


def _collect_feed_urls() -> tuple[str, ...]:
    values: list[str] = []
    single = os.getenv("NEWS_RECAP_RSS_FEED_URL", "").strip()
    if single:
        values.append(single)
    csv_list = os.getenv("NEWS_RECAP_RSS_FEED_URLS", "").strip()
    if csv_list:
        values.extend(part.strip() for part in csv_list.split(","))
    return _normalize_feed_urls(values)


def _collect_feed_item_overrides() -> dict[str, int]:
    raw = os.getenv("NEWS_RECAP_RSS_FEED_ITEMS", "").strip()
    if not raw:
        return {}

    overrides: dict[str, int] = {}
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "|" not in token:
            raise ValueError(
                "Invalid NEWS_RECAP_RSS_FEED_ITEMS entry: "
                f"{token!r}. Expected format '<feed_url>|<items>'.",
            )
        feed_url, items_raw = token.rsplit("|", 1)
        feed_url = feed_url.strip()
        items_raw = items_raw.strip()
        _validate_feed_url(feed_url)
        try:
            items = int(items_raw)
        except ValueError as error:
            raise ValueError(
                f"Invalid NEWS_RECAP_RSS_FEED_ITEMS value for {feed_url!r}: {items_raw!r}",
            ) from error
        if items <= 0:
            raise ValueError(
                "Invalid NEWS_RECAP_RSS_FEED_ITEMS value for "
                f"{feed_url!r}: {items!r} (must be > 0)",
            )
        overrides[feed_url] = items
    return overrides


def _default_agent_max_parallel() -> dict[str, int]:
    return {"codex": 3, "claude": 2, "gemini": 3}


_NO_THINKING = {"MAX_THINKING_TOKENS": "0"}
_MAX_OUTPUT = {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}
# Caps the hidden thinking scratchpad to a fixed token budget.
# Do NOT add CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING here — that flag disables the
# hidden scratchpad and forces the model to write its reasoning into stdout,
# which contaminates the structured output the parser expects.
_CAPPED_THINKING = {"CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1", "MAX_THINKING_TOKENS": "4000"}


def _default_task_model_map() -> dict[str, dict[str, Any]]:
    return {
        "recap_classify": {
            "codex": {"model": "--model gpt-5.2 -c model_reasoning_effort=low"},
            "claude": {"model": "--model sonnet --effort low", "env": _NO_THINKING},
            "gemini": {"model": "--model gemini-2.5-flash"},
        },
        "recap_enrich": {
            "codex": {"model": "--model gpt-5.2 -c model_reasoning_effort=low"},
            "claude": {"model": "--model sonnet --effort low", "env": _NO_THINKING},
            "gemini": {"model": "--model gemini-2.5-flash"},
        },
        "recap_dedup": {
            "codex": {"model": "--model gpt-5.2 -c model_reasoning_effort=low"},
            "claude": {"model": "--model sonnet --effort low", "env": _NO_THINKING},
            "gemini": {"model": "--model gemini-2.5-flash"},
        },
        "recap_oneshot_digest": {
            "codex": {"model": "--model gpt-5.2 -c model_reasoning_effort=low"},
            "claude": {"model": "--model sonnet --effort low", "env": _MAX_OUTPUT},
            "gemini": {"model": "--model gemini-2.5-flash"},
        },
        "recap_merge_sections": {
            "codex": {"model": "--model gpt-5.2 -c model_reasoning_effort=low"},
            "claude": {"model": "--model sonnet --effort low"},
            "gemini": {"model": "--model gemini-2.5-flash"},
        },
        "recap_refine_layout": {
            "codex": {"model": "--model gpt-5.2 -c model_reasoning_effort=low"},
            "claude": {"model": "--model sonnet --effort low"},
            "gemini": {"model": "--model gemini-2.5-flash"},
        },
    }


def _default_api_model_map() -> dict[str, str]:
    return {
        "recap_classify": "claude-haiku-4-5-20251001",
        "recap_enrich": "claude-haiku-4-5-20251001",
        "recap_dedup": "claude-haiku-4-5-20251001",
        "recap_oneshot_digest": "claude-haiku-4-5-20251001",
        "recap_merge_sections": "claude-sonnet-4-6",
        "recap_refine_layout": "claude-haiku-4-5-20251001",
    }


def _collect_api_model_map() -> dict[str, str]:
    """Build task → API model ID map from env or defaults.

    Env format (CSV of ``task_type=model_id``):
        ``NEWS_RECAP_API_MODEL_MAP=recap_oneshot_digest=claude-sonnet-4-6,recap_classify=claude-haiku-4-5-20251001``
    """
    raw = os.getenv("NEWS_RECAP_API_MODEL_MAP", "").strip()
    if not raw:
        return _default_api_model_map()

    base = _default_api_model_map()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(
                "Invalid NEWS_RECAP_API_MODEL_MAP entry: "
                f"{token!r}. Expected format '<task_type>=<model_id>'.",
            )
        task_type, model_id = token.split("=", 1)
        task_type = task_type.strip().lower()
        model_id = model_id.strip()
        if not task_type or not model_id:
            raise ValueError(f"Invalid NEWS_RECAP_API_MODEL_MAP entry: {token!r}")
        base[task_type] = model_id
    return base


def _collect_task_model_map() -> dict[str, dict[str, Any]]:
    """Build task → agent → model overrides from env or defaults.

    Env format (CSV of ``task_type:agent=model_flags``):
        ``NEWS_RECAP_LLM_TASK_MODEL_MAP=recap_oneshot_digest:codex=--model gpt-5.2 ...``
    """
    raw = os.getenv("NEWS_RECAP_LLM_TASK_MODEL_MAP", "").strip()
    if not raw:
        return _default_task_model_map()

    mapping: dict[str, dict[str, Any]] = {}
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "=" not in token or ":" not in token.split("=", 1)[0]:
            raise ValueError(
                "Invalid NEWS_RECAP_LLM_TASK_MODEL_MAP entry: "
                f"{token!r}. Expected format '<task_type>:<agent>=<model_flags>'.",
            )
        key, model = token.split("=", 1)
        task_type, agent = key.rsplit(":", 1)
        task_type = task_type.strip().lower()
        agent = agent.strip().lower()
        if not task_type or not agent:
            raise ValueError(f"Invalid NEWS_RECAP_LLM_TASK_MODEL_MAP key: {key!r}")
        mapping.setdefault(task_type, {})[agent] = {"model": model.strip()}
    return mapping


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


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value!r}")


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
