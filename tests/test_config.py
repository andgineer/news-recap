from __future__ import annotations

from os import environ

import allure
import pytest

from news_recap.config import (
    IngestionSettings,
    RssSettings,
    Settings,
)

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


def test_from_env_parses_gc_retention_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_GC_RETENTION_DAYS", "14")
    settings = Settings.from_env()
    assert settings.ingestion.gc_retention_days == 14


def test_from_env_parses_digest_lookback_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_DIGEST_LOOKBACK_DAYS", "5")
    settings = Settings.from_env()
    assert settings.ingestion.digest_lookback_days == 5


def test_validate_rejects_zero_gc_retention_days() -> None:
    settings = Settings(ingestion=IngestionSettings(gc_retention_days=0))
    with pytest.raises(ValueError, match="GC_RETENTION_DAYS"):
        settings.validate()


def test_from_env_uses_codex_as_default_llm_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_LLM_DEFAULT_AGENT", raising=False)
    monkeypatch.delenv("NEWS_RECAP_LLM_TASK_MODEL_MAP", raising=False)
    settings = Settings.from_env()
    assert settings.orchestrator.default_agent == "codex"
    task_map = settings.orchestrator.task_model_map
    assert "recap_classify" in task_map
    assert "recap_enrich" in task_map
    assert "recap_map" in task_map
    assert "recap_reduce" in task_map
    assert task_map["recap_classify"]["codex"] == "--model gpt-5.2 -c model_reasoning_effort=low"
    assert task_map["recap_reduce"]["codex"] == "--model gpt-5.2 -c model_reasoning_effort=low"
    assert task_map["recap_reduce"]["gemini"] == "--model gemini-2.5-pro"
    assert settings.orchestrator.codex_command_template == (
        "codex exec --sandbox workspace-write "
        "-c sandbox_workspace_write.network_access=true "
        '{model} "Read your task from {prompt_file} and execute it."'
    )
    assert settings.orchestrator.claude_command_template == (
        "claude -p {model} --permission-mode dontAsk "
        '--allowed-tools "Read,Write,Edit,WebFetch,'
        'Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" '
        '-- "Read your task from {prompt_file} and execute it."'
    )
    assert settings.orchestrator.gemini_command_template == (
        "gemini {model} --approval-mode auto_edit "
        '--prompt "Read your task from {prompt_file} and execute it."'
    )


def test_from_env_rejects_empty_worker_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKER_ID", "   ")
    with pytest.raises(ValueError, match="WORKER_ID"):
        Settings.from_env()


# ---------------------------------------------------------------------------
# API backend settings
# ---------------------------------------------------------------------------


def test_from_env_defaults_execution_backend_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_EXECUTION_BACKEND", raising=False)
    settings = Settings.from_env()
    assert settings.orchestrator.execution_backend == "cli"


def test_from_env_api_backend_requires_claude_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_EXECUTION_BACKEND", "api")
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex")
    with pytest.raises(ValueError) as exc_info:
        Settings.from_env()
    msg = str(exc_info.value)
    assert "execution_backend=api requires default_agent=claude" in msg
    assert "NEWS_RECAP_LLM_DEFAULT_AGENT=claude" in msg
    assert "codex" in msg


def test_from_env_api_backend_with_claude_agent_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_EXECUTION_BACKEND", "api")
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "claude")
    settings = Settings.from_env()
    assert settings.orchestrator.execution_backend == "api"
    assert settings.orchestrator.default_agent == "claude"


def test_validate_rejects_invalid_execution_backend() -> None:
    from news_recap.config import OrchestratorSettings

    settings = Settings(orchestrator=OrchestratorSettings(execution_backend="grpc"))
    with pytest.raises(ValueError, match="EXECUTION_BACKEND"):
        settings.validate()


def test_from_env_api_backend_skips_command_template_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In api mode, empty command templates should not fail validation."""
    monkeypatch.setenv("NEWS_RECAP_EXECUTION_BACKEND", "api")
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "claude")
    monkeypatch.setenv("NEWS_RECAP_CODEX_COMMAND_TEMPLATE", "  ")  # empty — would fail in cli mode
    # Should not raise
    settings = Settings.from_env()
    assert settings.orchestrator.execution_backend == "api"


def test_api_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_API_MAX_PARALLEL", raising=False)
    monkeypatch.delenv("NEWS_RECAP_API_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("NEWS_RECAP_API_CONCURRENCY_RECOVERY_SUCCESSES", raising=False)
    monkeypatch.delenv("NEWS_RECAP_API_RETRY_MAX_BACKOFF_SECONDS", raising=False)
    monkeypatch.delenv("NEWS_RECAP_API_RETRY_JITTER_SECONDS", raising=False)
    monkeypatch.delenv("NEWS_RECAP_API_DOWNSHIFT_PAUSE_SECONDS", raising=False)
    settings = Settings.from_env()
    orch = settings.orchestrator
    assert orch.api_max_parallel == 5
    assert orch.api_timeout_seconds == 120
    assert orch.api_concurrency_recovery_successes == 10
    assert orch.api_retry_max_backoff_seconds == 60.0
    assert orch.api_retry_jitter_seconds == 5.0
    assert orch.api_downshift_pause_seconds == 2.0


@pytest.mark.parametrize(
    ("env_var", "bad_value", "match"),
    [
        ("NEWS_RECAP_API_MAX_PARALLEL", "0", "API_MAX_PARALLEL"),
        ("NEWS_RECAP_API_TIMEOUT_SECONDS", "0", "API_TIMEOUT_SECONDS"),
        (
            "NEWS_RECAP_API_CONCURRENCY_RECOVERY_SUCCESSES",
            "0",
            "API_CONCURRENCY_RECOVERY_SUCCESSES",
        ),
        ("NEWS_RECAP_API_RETRY_MAX_BACKOFF_SECONDS", "-1", "API_RETRY_MAX_BACKOFF_SECONDS"),
        ("NEWS_RECAP_API_RETRY_JITTER_SECONDS", "-1", "API_RETRY_JITTER_SECONDS"),
        ("NEWS_RECAP_API_DOWNSHIFT_PAUSE_SECONDS", "-1", "API_DOWNSHIFT_PAUSE_SECONDS"),
    ],
)
def test_validate_rejects_invalid_api_runtime_limits(
    monkeypatch: pytest.MonkeyPatch, env_var: str, bad_value: str, match: str
) -> None:
    monkeypatch.setenv(env_var, bad_value)
    with pytest.raises(ValueError, match=match):
        Settings.from_env()


def test_validate_execution_backend_whitespace_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execution_backend with surrounding whitespace must be normalized before use."""
    monkeypatch.setenv("NEWS_RECAP_EXECUTION_BACKEND", "api ")
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "claude")
    settings = Settings.from_env()
    from news_recap.recap.agents.routing import RoutingDefaults

    rd = RoutingDefaults.from_settings(settings.orchestrator)
    assert rd.execution_backend == "api"


def test_api_model_map_default_has_all_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_API_MODEL_MAP", raising=False)
    settings = Settings.from_env()
    model_map = settings.orchestrator.api_model_map
    expected_tasks = {
        "recap_classify",
        "recap_enrich",
        "recap_dedup",
        "recap_map",
        "recap_reduce",
        "recap_split",
        "recap_group_sections",
        "recap_summarize",
    }
    assert expected_tasks == set(model_map.keys())


def test_api_model_map_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEWS_RECAP_API_MODEL_MAP",
        "recap_reduce=claude-opus-4-6,recap_classify=claude-haiku-4-5-20251001",
    )
    settings = Settings.from_env()
    assert settings.orchestrator.api_model_map["recap_reduce"] == "claude-opus-4-6"
    assert settings.orchestrator.api_model_map["recap_classify"] == "claude-haiku-4-5-20251001"
