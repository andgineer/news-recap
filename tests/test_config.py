from __future__ import annotations

from os import environ

import allure
import pytest

from news_recap.config import IngestionSettings, RssSettings, Settings

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Persist & Run Accounting"),
]


def test_validate_for_rss_requires_at_least_one_feed_url() -> None:
    settings = Settings(rss=RssSettings(feed_urls=()))

    with pytest.raises(ValueError, match="At least one RSS feed URL is required"):
        settings.validate_for_rss()


def test_validate_for_rss_rejects_invalid_feed_url() -> None:
    settings = Settings(rss=RssSettings(feed_urls=("https://example.com/feed.xml",)))

    with pytest.raises(ValueError, match="Invalid RSS feed URL"):
        settings.validate_for_rss(override_feed_urls=("ftp://example.com/feed.xml",))


def test_validate_for_rss_accepts_absolute_http_and_https_urls() -> None:
    settings = Settings(rss=RssSettings(feed_urls=("https://example.com/feed.xml",)))
    settings.validate_for_rss()
    settings.validate_for_rss(
        override_feed_urls=("http://example.com/feed.xml", "https://example.com/feed2.xml"),
    )


def test_validate_for_rss_rejects_non_positive_default_items_per_feed() -> None:
    settings = Settings(
        rss=RssSettings(
            feed_urls=("https://example.com/feed.xml",),
            default_items_per_feed=0,
        ),
    )

    with pytest.raises(ValueError, match="DEFAULT_ITEMS_PER_FEED"):
        settings.validate_for_rss()


def test_validate_for_rss_rejects_non_positive_per_feed_override() -> None:
    settings = Settings(
        rss=RssSettings(
            feed_urls=("https://example.com/feed.xml",),
            per_feed_items={"https://example.com/feed.xml": -1},
        ),
    )

    with pytest.raises(ValueError, match="Per-feed RSS items override"):
        settings.validate_for_rss()


def test_validate_for_rss_rejects_non_positive_active_run_stale_after_seconds() -> None:
    settings = Settings(
        ingestion=IngestionSettings(active_run_stale_after_seconds=0),
        rss=RssSettings(feed_urls=("https://example.com/feed.xml",)),
    )

    with pytest.raises(ValueError, match="ACTIVE_RUN_STALE_AFTER_SECONDS"):
        settings.validate_for_rss()


def test_validate_for_rss_rejects_negative_article_retention_days() -> None:
    settings = Settings(
        ingestion=IngestionSettings(article_retention_days=-1),
        rss=RssSettings(feed_urls=("https://example.com/feed.xml",)),
    )

    with pytest.raises(ValueError, match="ARTICLE_RETENTION_DAYS"):
        settings.validate_for_rss()


def test_from_env_parses_per_feed_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEWS_RECAP_RSS_FEED_URLS", "https://a.example/feed.xml,https://b.example/feed.xml"
    )
    monkeypatch.setenv(
        "NEWS_RECAP_RSS_FEED_ITEMS",
        "https://a.example/feed.xml|5000,https://b.example/feed.xml|123",
    )
    monkeypatch.setenv("NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED", "10000")

    settings = Settings.from_env()
    assert settings.rss.default_items_per_feed == 10000
    assert settings.rss.per_feed_items == {
        "https://a.example/feed.xml": 5000,
        "https://b.example/feed.xml": 123,
    }

    # Cleanup explicit env keys set in this test for isolation in local runs.
    environ.pop("NEWS_RECAP_RSS_FEED_URLS", None)
    environ.pop("NEWS_RECAP_RSS_FEED_ITEMS", None)
    environ.pop("NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED", None)


def test_from_env_parses_article_retention_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_ARTICLE_RETENTION_DAYS", "14")
    settings = Settings.from_env()
    assert settings.ingestion.article_retention_days == 14


def test_from_env_uses_codex_as_default_llm_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_LLM_DEFAULT_AGENT", raising=False)
    monkeypatch.delenv("NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP", raising=False)
    monkeypatch.delenv("NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE", raising=False)
    monkeypatch.delenv("NEWS_RECAP_LLM_CLAUDE_COMMAND_TEMPLATE", raising=False)
    monkeypatch.delenv("NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE", raising=False)
    settings = Settings.from_env()
    assert settings.orchestrator.default_agent == "codex"
    assert settings.orchestrator.task_type_profile_map == {
        "highlights": "fast",
        "story": "quality",
        "qa": "fast",
    }
    assert settings.orchestrator.codex_command_template == (
        "codex exec --sandbox workspace-write "
        "-c sandbox_workspace_write.network_access=true "
        '-c model_reasoning_effort=high --model {model} "task_manifest={task_manifest}\\n{prompt}"'
    )
    assert settings.orchestrator.claude_command_template == (
        "claude -p --model {model} --permission-mode dontAsk "
        '--allowed-tools "Read,Write,Edit,WebFetch,'
        'Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" '
        '-- "task_manifest={task_manifest}\\n{prompt}"'
    )
    assert (
        settings.orchestrator.gemini_command_template
        == 'gemini --model {model} --approval-mode auto_edit --prompt "task_manifest={task_manifest}\\n{prompt}"'
    )
    assert settings.orchestrator.gemini_model_fast == "gemini-2.5-flash"
    assert settings.orchestrator.gemini_model_quality == "gemini-2.5-pro"


def test_from_env_parses_task_type_profile_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP",
        "highlights=fast,story=quality,digest=fast",
    )
    settings = Settings.from_env()
    assert settings.orchestrator.task_type_profile_map == {
        "highlights": "fast",
        "story": "quality",
        "digest": "fast",
    }


def test_from_env_rejects_invalid_task_type_profile_map_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP", "highlights=cheap")
    with pytest.raises(ValueError, match="expected fast or quality"):
        Settings.from_env()


def test_from_env_parses_sqlite_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_SQLITE_BUSY_TIMEOUT_MS", "12345")
    settings = Settings.from_env()
    assert settings.sqlite_busy_timeout_ms == 12345


def test_from_env_rejects_non_positive_sqlite_busy_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_RECAP_SQLITE_BUSY_TIMEOUT_MS", "0")
    with pytest.raises(ValueError, match="SQLITE_BUSY_TIMEOUT_MS"):
        Settings.from_env()


def test_from_env_rejects_unsupported_command_template_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE", "codex exec {unknown}")
    with pytest.raises(ValueError, match="unsupported placeholder"):
        Settings.from_env()


def test_from_env_rejects_command_template_without_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE", "gemini --help")
    with pytest.raises(ValueError, match="must include at least one placeholder"):
        Settings.from_env()


def test_from_env_rejects_command_template_without_task_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE", "codex --model {model} {prompt}")
    with pytest.raises(ValueError, match="required placeholder \\{task_manifest\\}"):
        Settings.from_env()


def test_from_env_rejects_empty_worker_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKER_ID", "   ")
    with pytest.raises(ValueError, match="WORKER_ID"):
        Settings.from_env()
