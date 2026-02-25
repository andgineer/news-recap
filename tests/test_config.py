from __future__ import annotations

from os import environ

import allure
import pytest

from news_recap.config import (
    _DEFAULT_PREFECT_API_URL,
    IngestionSettings,
    PrefectMode,
    RssSettings,
    Settings,
    _probe_prefect_server,
    configure_prefect_runtime,
    resolve_prefect_mode,
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
# Prefect runtime mode
# ---------------------------------------------------------------------------


class TestResolvePrefectMode:
    def test_defaults_to_ephemeral(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEWS_RECAP_PREFECT_MODE", raising=False)
        assert resolve_prefect_mode() == PrefectMode.EPHEMERAL

    def test_explicit_ephemeral(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEWS_RECAP_PREFECT_MODE", "ephemeral")
        assert resolve_prefect_mode() == PrefectMode.EPHEMERAL

    def test_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEWS_RECAP_PREFECT_MODE", "server")
        assert resolve_prefect_mode() == PrefectMode.SERVER

    def test_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEWS_RECAP_PREFECT_MODE", "auto")
        assert resolve_prefect_mode() == PrefectMode.AUTO

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEWS_RECAP_PREFECT_MODE", "  SERVER  ")
        assert resolve_prefect_mode() == PrefectMode.SERVER

    def test_invalid_value_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEWS_RECAP_PREFECT_MODE", "cloud")
        with pytest.raises(ValueError, match="Invalid NEWS_RECAP_PREFECT_MODE"):
            resolve_prefect_mode()


class TestConfigurePrefectRuntime:
    def test_ephemeral_unsets_api_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFECT_API_URL", "http://localhost:4200/api")
        result = configure_prefect_runtime(PrefectMode.EPHEMERAL)
        assert result == PrefectMode.EPHEMERAL
        assert "PREFECT_API_URL" not in environ

    def test_server_uses_default_url_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PREFECT_API_URL", raising=False)
        probed: list[str] = []
        monkeypatch.setattr(
            "news_recap.config._probe_prefect_server",
            lambda url: (probed.append(url), True)[1],
        )
        result = configure_prefect_runtime(PrefectMode.SERVER)
        assert result == PrefectMode.SERVER
        assert probed == [_DEFAULT_PREFECT_API_URL]
        assert environ["PREFECT_API_URL"] == _DEFAULT_PREFECT_API_URL

    def test_server_uses_explicit_url_over_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom = "http://prefect.local:4200/api"
        monkeypatch.setenv("PREFECT_API_URL", custom)
        probed: list[str] = []
        monkeypatch.setattr(
            "news_recap.config._probe_prefect_server",
            lambda url: (probed.append(url), True)[1],
        )
        result = configure_prefect_runtime(PrefectMode.SERVER)
        assert result == PrefectMode.SERVER
        assert probed == [custom]
        assert environ["PREFECT_API_URL"] == custom

    def test_server_fails_fast_when_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFECT_API_URL", "http://localhost:4200/api")
        monkeypatch.setattr("news_recap.config._probe_prefect_server", lambda _: False)
        with pytest.raises(RuntimeError, match="not reachable"):
            configure_prefect_runtime(PrefectMode.SERVER)

    def test_server_fails_fast_with_default_url_when_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PREFECT_API_URL", raising=False)
        monkeypatch.setattr("news_recap.config._probe_prefect_server", lambda _: False)
        with pytest.raises(RuntimeError, match="not reachable"):
            configure_prefect_runtime(PrefectMode.SERVER)

    def test_auto_falls_back_to_ephemeral(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFECT_API_URL", "http://localhost:4200/api")
        monkeypatch.setattr("news_recap.config._probe_prefect_server", lambda _: False)
        result = configure_prefect_runtime(PrefectMode.AUTO)
        assert result == PrefectMode.EPHEMERAL
        assert "PREFECT_API_URL" not in environ

    def test_auto_uses_server_when_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFECT_API_URL", "http://localhost:4200/api")
        monkeypatch.setattr("news_recap.config._probe_prefect_server", lambda _: True)
        result = configure_prefect_runtime(PrefectMode.AUTO)
        assert result == PrefectMode.SERVER

    def test_auto_probes_default_url_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PREFECT_API_URL", raising=False)
        probed: list[str] = []
        monkeypatch.setattr(
            "news_recap.config._probe_prefect_server",
            lambda url: (probed.append(url), True)[1],
        )
        result = configure_prefect_runtime(PrefectMode.AUTO)
        assert result == PrefectMode.SERVER
        assert probed == [_DEFAULT_PREFECT_API_URL]
        assert environ["PREFECT_API_URL"] == _DEFAULT_PREFECT_API_URL

    def test_auto_ephemeral_when_default_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PREFECT_API_URL", raising=False)
        monkeypatch.setattr("news_recap.config._probe_prefect_server", lambda _: False)
        result = configure_prefect_runtime(PrefectMode.AUTO)
        assert result == PrefectMode.EPHEMERAL


class TestProbePrefectServer:
    def test_returns_true_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        def _mock_get(url: str, *, timeout: float) -> httpx.Response:
            assert url == "http://localhost:4200/api/health"
            return httpx.Response(200)

        monkeypatch.setattr("httpx.get", _mock_get)
        assert _probe_prefect_server("http://localhost:4200/api") is True

    def test_returns_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        def _mock_get(url: str, *, timeout: float) -> httpx.Response:
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.get", _mock_get)
        assert _probe_prefect_server("http://localhost:4200/api") is False

    def test_returns_false_on_non_success_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        def _mock_get(url: str, *, timeout: float) -> httpx.Response:
            return httpx.Response(503)

        monkeypatch.setattr("httpx.get", _mock_get)
        assert _probe_prefect_server("http://localhost:4200/api") is False

    def test_strips_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        def _mock_get(url: str, *, timeout: float) -> httpx.Response:
            assert url == "http://localhost:4200/api/health"
            return httpx.Response(200)

        monkeypatch.setattr("httpx.get", _mock_get)
        assert _probe_prefect_server("http://localhost:4200/api/") is True
