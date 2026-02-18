"""Runtime configuration for ingestion and dedup pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


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
class Settings:
    """Application settings grouped by domain concerns."""

    db_path: Path = Path(".news_recap.db")
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    rss: RssSettings = field(default_factory=RssSettings)
    user_context: UserContextSettings = field(default_factory=UserContextSettings)

    @classmethod
    def from_env(cls, db_path: Path | None = None) -> Settings:
        """Load settings from environment with sane defaults for local development."""

        rss_urls = _collect_feed_urls()
        return cls(
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
        )

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
