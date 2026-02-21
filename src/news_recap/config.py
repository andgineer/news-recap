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
    article_retention_days: int = 30


@dataclass(slots=True)
class DedupSettings:
    """Semantic deduplication settings."""

    enabled: bool = True
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


@dataclass(slots=True)
class UserContextSettings:
    """User context settings."""

    user_id: str = "default_user"
    user_name: str = "Default User"


@dataclass(slots=True)
class OrchestratorSettings:
    """CLI orchestrator settings."""

    workdir_root: Path = Path(".news_recap_workdir")
    default_agent: str = "codex"
    task_type_profile_map: dict[str, str] = field(
        default_factory=lambda: {
            "highlights": "fast",
            "story": "quality",
            "qa": "fast",
            "recap_classify": "fast",
            "recap_enrich": "fast",
            "recap_group": "fast",
            "recap_enrich_full": "fast",
            "recap_synthesize": "quality",
            "recap_compose": "quality",
        },
    )
    codex_command_template: str = (
        "codex exec --sandbox workspace-write "
        "-c sandbox_workspace_write.network_access=true "
        '{model} "Read your task from {prompt_file} and execute it."'
    )
    claude_command_template: str = (
        "claude -p --model {model} --permission-mode dontAsk "
        '--allowed-tools "Read,Write,Edit,WebFetch,'
        'Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" '
        '-- "Read your task from {prompt_file} and execute it."'
    )
    gemini_command_template: str = (
        "gemini --model {model} --approval-mode auto_edit "
        '--prompt "Read your task from {prompt_file} and execute it."'
    )
    codex_model_fast: str = "--model gpt-5.2 -c model_reasoning_effort=medium"
    codex_model_quality: str = "--model gpt-5.2 -c model_reasoning_effort=high"
    claude_model_fast: str = "sonnet"
    claude_model_quality: str = "opus"
    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_quality: str = "gemini-2.5-pro"
    worker_id: str = "worker-default"
    poll_interval_seconds: float = 2.0
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    worker_stale_attempt_seconds: int = 1_800
    worker_graceful_shutdown_seconds: int = 30
    backend_capability_mode: str = "manifest_native"
    qa_lookback_days: int = 3
    retrieval_top_k: int = 40
    retrieval_max_articles: int = 80
    retrieval_token_budget: int = 12_000
    retrieval_char_budget: int = 60_000


@dataclass(slots=True)
class Settings:
    """Application settings grouped by domain concerns."""

    db_path: Path = Path(".news_recap.db")
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    rss: RssSettings = field(default_factory=RssSettings)
    user_context: UserContextSettings = field(default_factory=UserContextSettings)
    orchestrator: OrchestratorSettings = field(default_factory=OrchestratorSettings)
    sqlite_busy_timeout_ms: int = 5_000

    @classmethod
    def from_env(cls, db_path: Path | None = None) -> Settings:
        """Load settings from environment with sane defaults for local development."""

        rss_urls = _collect_feed_urls()
        settings = cls(
            db_path=db_path or Path(os.getenv("NEWS_RECAP_DB_PATH", ".news_recap.db")),
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
                article_retention_days=int(os.getenv("NEWS_RECAP_ARTICLE_RETENTION_DAYS", "30")),
            ),
            dedup=DedupSettings(
                enabled=_env_bool("NEWS_RECAP_DEDUP_ENABLED", default=True),
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
            user_context=UserContextSettings(
                user_id=os.getenv("NEWS_RECAP_USER_ID", "default_user"),
                user_name=os.getenv("NEWS_RECAP_USER_NAME", "Default User"),
            ),
            orchestrator=OrchestratorSettings(
                workdir_root=Path(
                    os.getenv(
                        "NEWS_RECAP_LLM_WORKDIR_ROOT",
                        ".news_recap_workdir",
                    ),
                ),
                default_agent=os.getenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex"),
                task_type_profile_map=_collect_task_type_profile_map(),
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
                backend_capability_mode=os.getenv(
                    "NEWS_RECAP_BACKEND_CAPABILITY_MODE",
                    "manifest_native",
                ),
                qa_lookback_days=int(os.getenv("NEWS_RECAP_QA_LOOKBACK_DAYS", "3")),
                retrieval_top_k=int(os.getenv("NEWS_RECAP_RETRIEVAL_TOP_K", "40")),
                retrieval_max_articles=int(
                    os.getenv("NEWS_RECAP_RETRIEVAL_MAX_ARTICLES", "80"),
                ),
                retrieval_token_budget=int(
                    os.getenv("NEWS_RECAP_RETRIEVAL_TOKEN_BUDGET", "12000"),
                ),
                retrieval_char_budget=int(
                    os.getenv("NEWS_RECAP_RETRIEVAL_CHAR_BUDGET", "60000"),
                ),
            ),
            sqlite_busy_timeout_ms=int(
                os.getenv("NEWS_RECAP_SQLITE_BUSY_TIMEOUT_MS", "5000"),
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
        if self.sqlite_busy_timeout_ms <= 0:
            raise ValueError("NEWS_RECAP_SQLITE_BUSY_TIMEOUT_MS must be > 0.")
        if self.ingestion.active_run_stale_after_seconds <= 0:
            raise ValueError("NEWS_RECAP_ACTIVE_RUN_STALE_AFTER_SECONDS must be > 0.")
        if self.ingestion.article_retention_days < 0:
            raise ValueError("NEWS_RECAP_ARTICLE_RETENTION_DAYS must be >= 0.")
        if not (0.0 < self.dedup.threshold <= 1.0):
            raise ValueError("NEWS_RECAP_DEDUP_THRESHOLD must be in (0, 1].")

    def _validate_orchestrator_routing(self) -> None:
        supported_agents = {"codex", "claude", "gemini"}
        default_agent = self.orchestrator.default_agent.strip().lower()
        if default_agent not in supported_agents:
            raise ValueError(
                "NEWS_RECAP_LLM_DEFAULT_AGENT must be one of: codex, claude, gemini.",
            )

        for task_type, profile in self.orchestrator.task_type_profile_map.items():
            normalized_task_type = task_type.strip().lower()
            normalized_profile = profile.strip().lower()
            if not normalized_task_type:
                raise ValueError("NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP contains empty task_type.")
            if normalized_profile not in {"fast", "quality"}:
                raise ValueError(
                    f"Unsupported model profile for task_type={task_type!r}: {profile!r}",
                )

        for name, template in (
            ("codex_command_template", self.orchestrator.codex_command_template),
            ("claude_command_template", self.orchestrator.claude_command_template),
            ("gemini_command_template", self.orchestrator.gemini_command_template),
        ):
            _validate_command_template(name=name, template=template)

        for field_name, model_id in (
            ("codex_model_fast", self.orchestrator.codex_model_fast),
            ("codex_model_quality", self.orchestrator.codex_model_quality),
            ("claude_model_fast", self.orchestrator.claude_model_fast),
            ("claude_model_quality", self.orchestrator.claude_model_quality),
            ("gemini_model_fast", self.orchestrator.gemini_model_fast),
            ("gemini_model_quality", self.orchestrator.gemini_model_quality),
        ):
            if not model_id.strip():
                raise ValueError(f"OrchestratorSettings.{field_name} must not be empty.")

        valid_capability_modes = {"manifest_native", "stdout_parser_fallback"}
        if self.orchestrator.backend_capability_mode not in valid_capability_modes:
            raise ValueError(
                f"NEWS_RECAP_BACKEND_CAPABILITY_MODE must be one of {valid_capability_modes}, "
                f"got {self.orchestrator.backend_capability_mode!r}.",
            )

    def _validate_orchestrator_runtime_limits(self) -> None:  # noqa: C901
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
        if self.orchestrator.qa_lookback_days <= 0:
            raise ValueError("NEWS_RECAP_QA_LOOKBACK_DAYS must be > 0.")
        if self.orchestrator.retrieval_top_k <= 0:
            raise ValueError("NEWS_RECAP_RETRIEVAL_TOP_K must be > 0.")
        if self.orchestrator.retrieval_max_articles <= 0:
            raise ValueError("NEWS_RECAP_RETRIEVAL_MAX_ARTICLES must be > 0.")
        if self.orchestrator.retrieval_token_budget <= 0:
            raise ValueError("NEWS_RECAP_RETRIEVAL_TOKEN_BUDGET must be > 0.")
        if self.orchestrator.retrieval_char_budget <= 0:
            raise ValueError("NEWS_RECAP_RETRIEVAL_CHAR_BUDGET must be > 0.")

    def validate_for_rss(self, override_feed_urls: tuple[str, ...] = ()) -> None:
        """Raise configuration error if RSS feed URLs are missing or invalid."""

        if self.ingestion.active_run_stale_after_seconds <= 0:
            raise ValueError("NEWS_RECAP_ACTIVE_RUN_STALE_AFTER_SECONDS must be > 0.")
        if self.ingestion.article_retention_days < 0:
            raise ValueError("NEWS_RECAP_ARTICLE_RETENTION_DAYS must be >= 0.")

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


def _collect_task_type_profile_map() -> dict[str, str]:
    default_map = (
        "highlights=fast,story=quality,qa=fast,"
        "recap_classify=fast,recap_enrich=fast,recap_group=fast,"
        "recap_enrich_full=fast,recap_synthesize=quality,recap_compose=quality"
    )
    raw = os.getenv("NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP", default_map).strip()
    if not raw:
        return {
            "highlights": "fast",
            "story": "quality",
            "qa": "fast",
            "recap_classify": "fast",
            "recap_enrich": "fast",
            "recap_group": "fast",
            "recap_enrich_full": "fast",
            "recap_synthesize": "quality",
            "recap_compose": "quality",
        }
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(
                "Invalid NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP entry: "
                f"{token!r}. Expected format '<task_type>=<profile>'.",
            )
        task_type, profile = token.split("=", 1)
        normalized_task_type = task_type.strip().lower()
        normalized_profile = profile.strip().lower()
        if not normalized_task_type:
            raise ValueError(
                f"Invalid NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP task_type: {token!r}",
            )
        if normalized_profile not in {"fast", "quality"}:
            raise ValueError(
                "Invalid NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP profile: "
                f"{normalized_profile!r} (expected fast or quality)",
            )
        mapping[normalized_task_type] = normalized_profile
    if not mapping:
        raise ValueError(
            "NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP resolved to empty mapping.",
        )
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
