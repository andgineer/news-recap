"""Runtime configuration for ingestion and dedup pipeline."""

from __future__ import annotations

import enum
import logging
import os
import string
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionSettings:
    """Generic ingestion-stage settings."""

    page_size: int = 50
    max_pages: int = 0
    active_run_stale_after_seconds: int = 1_800
    backfill_max_gaps: int = 10
    clean_text_max_chars: int = 12_000
    gc_retention_days: int = 7
    digest_lookback_days: int = 3
    min_resource_chars: int = 200


@dataclass(slots=True)
class DedupSettings:
    """Semantic deduplication settings."""

    enabled: bool = False
    threshold: float = 0.95
    model_name: str = "intfloat/multilingual-e5-small"
    allow_model_fallback: bool = False
    lookback_days: int = 3
    embedding_ttl_days: int = 7


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


_DEFAULT_CODEX_CMD = (
    "codex exec --sandbox workspace-write "
    "-c sandbox_workspace_write.network_access=true "
    '{model} "Read your task from {prompt_file} and execute it."'
)
_DEFAULT_CLAUDE_CMD = (
    "claude -p {model} --permission-mode dontAsk "
    '--allowed-tools "Read,Write,Edit,WebFetch,'
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

    workdir_root: Path = Path(".news_recap_workdir")
    default_agent: str = "codex"
    task_model_map: dict[str, dict[str, str]] = field(
        default_factory=lambda: _default_task_model_map(),
    )
    task_type_timeout_map: dict[str, int] = field(
        default_factory=lambda: {
            "recap_classify": 900,
            "recap_enrich": 600,
            "recap_map": 300,
            "recap_reduce": 600,
        },
    )
    codex_command_template: str = _DEFAULT_CODEX_CMD
    claude_command_template: str = _DEFAULT_CLAUDE_CMD
    gemini_command_template: str = _DEFAULT_GEMINI_CMD
    worker_id: str = "worker-default"
    poll_interval_seconds: float = 2.0
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    worker_stale_attempt_seconds: int = 1_800
    worker_graceful_shutdown_seconds: int = 30


@dataclass(slots=True)
class Settings:
    """Application settings grouped by domain concerns."""

    data_dir: Path = Path(".news_recap_data")
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    rss: RssSettings = field(default_factory=RssSettings)
    orchestrator: OrchestratorSettings = field(default_factory=OrchestratorSettings)

    @classmethod
    def from_env(cls, data_dir: Path | None = None) -> Settings:
        """Load settings from environment with sane defaults for local development."""

        rss_urls = _collect_feed_urls()
        settings = cls(
            data_dir=data_dir or Path(os.getenv("NEWS_RECAP_DATA_DIR", ".news_recap_data")),
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
                active_run_stale_after_seconds=int(
                    os.getenv("NEWS_RECAP_ACTIVE_RUN_STALE_AFTER_SECONDS", "1800"),
                ),
                backfill_max_gaps=int(os.getenv("NEWS_RECAP_BACKFILL_MAX_GAPS", "10")),
                clean_text_max_chars=int(os.getenv("NEWS_RECAP_CLEAN_TEXT_MAX_CHARS", "12000")),
                gc_retention_days=int(os.getenv("NEWS_RECAP_GC_RETENTION_DAYS", "7")),
                digest_lookback_days=int(os.getenv("NEWS_RECAP_DIGEST_LOOKBACK_DAYS", "3")),
                min_resource_chars=int(os.getenv("NEWS_RECAP_MIN_RESOURCE_CHARS", "200")),
            ),
            dedup=DedupSettings(
                enabled=_env_bool("NEWS_RECAP_DEDUP_ENABLED", default=False),
                threshold=float(os.getenv("NEWS_RECAP_DEDUP_THRESHOLD", "0.95")),
                model_name=os.getenv(
                    "NEWS_RECAP_DEDUP_MODEL_NAME",
                    "intfloat/multilingual-e5-small",
                ),
                allow_model_fallback=_env_bool(
                    "NEWS_RECAP_DEDUP_ALLOW_MODEL_FALLBACK",
                    default=False,
                ),
                lookback_days=int(os.getenv("NEWS_RECAP_DEDUP_LOOKBACK_DAYS", "3")),
                embedding_ttl_days=int(os.getenv("NEWS_RECAP_EMBEDDING_TTL_DAYS", "7")),
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
                workdir_root=Path(
                    os.getenv(
                        "NEWS_RECAP_LLM_WORKDIR_ROOT",
                        ".news_recap_workdir",
                    ),
                ),
                default_agent=os.getenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex"),
                codex_command_template=os.getenv(
                    "NEWS_RECAP_CODEX_COMMAND_TEMPLATE",
                    _DEFAULT_CODEX_CMD,
                ),
                claude_command_template=os.getenv(
                    "NEWS_RECAP_CLAUDE_COMMAND_TEMPLATE",
                    _DEFAULT_CLAUDE_CMD,
                ),
                gemini_command_template=os.getenv(
                    "NEWS_RECAP_GEMINI_COMMAND_TEMPLATE",
                    _DEFAULT_GEMINI_CMD,
                ),
                task_model_map=_collect_task_model_map(),
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
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate cross-domain runtime settings and fail fast on invalid config."""

        self._validate_storage_and_ingestion()
        self._validate_orchestrator_routing()
        self._validate_orchestrator_runtime_limits()

    def _validate_storage_and_ingestion(self) -> None:
        if self.ingestion.active_run_stale_after_seconds <= 0:
            raise ValueError("NEWS_RECAP_ACTIVE_RUN_STALE_AFTER_SECONDS must be > 0.")
        if self.ingestion.gc_retention_days < 1:
            raise ValueError("NEWS_RECAP_GC_RETENTION_DAYS must be >= 1.")
        if self.ingestion.digest_lookback_days < 1:
            raise ValueError("NEWS_RECAP_DIGEST_LOOKBACK_DAYS must be >= 1.")
        if not (0.0 < self.dedup.threshold <= 1.0):
            raise ValueError("NEWS_RECAP_DEDUP_THRESHOLD must be in (0, 1].")

    def _validate_orchestrator_routing(self) -> None:
        supported_agents = {"codex", "claude", "gemini"}
        default_agent = self.orchestrator.default_agent.strip().lower()
        if default_agent not in supported_agents:
            raise ValueError(
                "NEWS_RECAP_LLM_DEFAULT_AGENT must be one of: codex, claude, gemini.",
            )

        for task_type, agent_models in self.orchestrator.task_model_map.items():
            if not task_type.strip():
                raise ValueError("task_model_map contains empty task_type key.")
            for agent, model in agent_models.items():
                if agent not in supported_agents:
                    raise ValueError(
                        f"task_model_map[{task_type!r}] has unsupported agent: {agent!r}",
                    )
                if not model.strip():
                    raise ValueError(
                        f"task_model_map[{task_type!r}][{agent!r}] model must not be empty.",
                    )

        for name, template in (
            ("codex_command_template", self.orchestrator.codex_command_template),
            ("claude_command_template", self.orchestrator.claude_command_template),
            ("gemini_command_template", self.orchestrator.gemini_command_template),
        ):
            _validate_command_template(name=name, template=template)

    def _validate_orchestrator_runtime_limits(self) -> None:
        if not self.orchestrator.worker_id.strip():
            raise ValueError("NEWS_RECAP_LLM_WORKER_ID must not be empty.")
        if self.orchestrator.poll_interval_seconds < 0:
            raise ValueError("NEWS_RECAP_LLM_POLL_INTERVAL_SECONDS must be >= 0.")
        if self.orchestrator.retry_base_seconds < 0:
            raise ValueError("NEWS_RECAP_LLM_RETRY_BASE_SECONDS must be >= 0.")
        if self.orchestrator.retry_max_seconds < 0:
            raise ValueError("NEWS_RECAP_LLM_RETRY_MAX_SECONDS must be >= 0.")
        if self.orchestrator.retry_max_seconds < self.orchestrator.retry_base_seconds:
            raise ValueError(
                "NEWS_RECAP_LLM_RETRY_MAX_SECONDS must be >= NEWS_RECAP_LLM_RETRY_BASE_SECONDS.",
            )
        if self.orchestrator.worker_stale_attempt_seconds <= 0:
            raise ValueError("NEWS_RECAP_WORKER_STALE_ATTEMPT_SECONDS must be > 0.")
        if self.orchestrator.worker_graceful_shutdown_seconds <= 0:
            raise ValueError("NEWS_RECAP_WORKER_GRACEFUL_SHUTDOWN_SECONDS must be > 0.")

    def validate_for_rss(self, override_feed_urls: tuple[str, ...] = ()) -> None:
        """Raise configuration error if RSS feed URLs are missing or invalid."""

        if self.ingestion.active_run_stale_after_seconds <= 0:
            raise ValueError("NEWS_RECAP_ACTIVE_RUN_STALE_AFTER_SECONDS must be > 0.")

        effective_feed_urls = _normalize_feed_urls(override_feed_urls or self.rss.feed_urls)
        if not effective_feed_urls:
            raise ValueError(
                "At least one RSS feed URL is required. "
                "Set NEWS_RECAP_RSS_FEED_URLS or pass --feed-url.",
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


def _default_task_model_map() -> dict[str, dict[str, str]]:
    return {
        "recap_classify": {
            "codex": "--model gpt-5.2 -c model_reasoning_effort=low",
            "claude": "--model sonnet --effort low",
            "gemini": "--model gemini-2.5-flash",
        },
        "recap_enrich": {
            "codex": "--model gpt-5.2 -c model_reasoning_effort=low",
            "claude": "--model sonnet --effort low",
            "gemini": "--model gemini-2.5-flash",
        },
        "recap_map": {
            "codex": "--model gpt-5.2 -c model_reasoning_effort=low",
            "claude": "--model sonnet --effort low",
            "gemini": "--model gemini-2.5-flash",
        },
        "recap_reduce": {
            "codex": "--model gpt-5.2 -c model_reasoning_effort=high",
            "claude": "--model opus",
            "gemini": "--model gemini-2.5-pro",
        },
    }


def _collect_task_model_map() -> dict[str, dict[str, str]]:
    """Build task → agent → model overrides from env or defaults.

    Env format (CSV of ``task_type:agent=model_flags``):
        ``NEWS_RECAP_LLM_TASK_MODEL_MAP=recap_reduce:codex=--model gpt-5.2 ...``
    """
    raw = os.getenv("NEWS_RECAP_LLM_TASK_MODEL_MAP", "").strip()
    if not raw:
        return _default_task_model_map()

    mapping: dict[str, dict[str, str]] = {}
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
        mapping.setdefault(task_type, {})[agent] = model.strip()
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


# ---------------------------------------------------------------------------
# Prefect runtime mode
# ---------------------------------------------------------------------------


class PrefectMode(enum.Enum):
    """Execution mode for the Prefect-based recap pipeline."""

    EPHEMERAL = "ephemeral"
    SERVER = "server"
    AUTO = "auto"


def resolve_prefect_mode() -> PrefectMode:
    """Resolve Prefect execution mode from ``NEWS_RECAP_PREFECT_MODE``."""
    raw = os.getenv("NEWS_RECAP_PREFECT_MODE", "").strip().lower()
    if not raw or raw == "ephemeral":
        return PrefectMode.EPHEMERAL
    if raw == "server":
        return PrefectMode.SERVER
    if raw == "auto":
        return PrefectMode.AUTO
    raise ValueError(
        f"Invalid NEWS_RECAP_PREFECT_MODE: {raw!r}. Use ephemeral, server, or auto.",
    )


def configure_prefect_runtime(mode: PrefectMode) -> PrefectMode:
    """Configure Prefect for *mode* and return the effective mode.

    * ``EPHEMERAL``: unset ``PREFECT_API_URL``; run locally.
    * ``SERVER``: require ``PREFECT_API_URL``; fail fast if unreachable.
    * ``AUTO``: probe ``PREFECT_API_URL`` (≤500 ms); fall back to ephemeral.
    """
    if mode == PrefectMode.EPHEMERAL:
        os.environ.pop("PREFECT_API_URL", None)
        return PrefectMode.EPHEMERAL

    api_url = os.getenv("PREFECT_API_URL", "").strip()

    if mode == PrefectMode.SERVER:
        if not api_url:
            raise ValueError(
                "NEWS_RECAP_PREFECT_MODE=server requires PREFECT_API_URL to be set.",
            )
        if not _probe_prefect_server(api_url):
            raise RuntimeError(
                f"Prefect server at {api_url} is not reachable (mode=server, fail-fast).",
            )
        return PrefectMode.SERVER

    if api_url and _probe_prefect_server(api_url):
        logger.info("Prefect server reachable at %s — using server mode", api_url)
        return PrefectMode.SERVER

    logger.info("No reachable Prefect server — falling back to ephemeral mode")
    os.environ.pop("PREFECT_API_URL", None)
    return PrefectMode.EPHEMERAL


_PROBE_TIMEOUT_SECONDS = 0.5


def _probe_prefect_server(api_url: str) -> bool:
    """Return True if the Prefect server health endpoint responds within timeout.

    ``PREFECT_API_URL`` conventionally includes ``/api`` already
    (e.g. ``http://localhost:4200/api``), so we append only ``/health``.
    """
    import httpx

    try:
        health_url = f"{api_url.rstrip('/')}/health"
        resp = httpx.get(health_url, timeout=_PROBE_TIMEOUT_SECONDS)
        return resp.is_success  # noqa: TRY300
    except (httpx.HTTPError, OSError):
        return False
