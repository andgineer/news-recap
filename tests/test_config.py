from __future__ import annotations

from os import environ
from pathlib import Path

import allure
import pytest

from news_recap.config import (
    IngestionSettings,
    RssSettings,
    Settings,
    resolve_typesafe_api_key,
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


def test_digest_lookback_days_default_is_two() -> None:
    settings = Settings.from_env()
    assert settings.ingestion.digest_lookback_days == 2


def test_from_env_parses_digest_lookback_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_DIGEST_LOOKBACK_DAYS", "5")
    settings = Settings.from_env()
    assert settings.ingestion.digest_lookback_days == 5


def test_validate_rejects_zero_gc_retention_days() -> None:
    settings = Settings(ingestion=IngestionSettings(gc_retention_days=0))
    with pytest.raises(ValueError, match="GC_RETENTION_DAYS"):
        settings.validate()


def test_from_env_uses_codex_as_default_llm_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("NEWS_RECAP_LLM_DEFAULT_AGENT", raising=False)
    monkeypatch.delenv("NEWS_RECAP_LLM_TASK_MODEL_MAP", raising=False)
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.orchestrator.default_agent == "codex"
    task_map = settings.orchestrator.task_model_map
    assert "recap_classify" in task_map
    assert "recap_enrich" in task_map
    assert "recap_oneshot_digest" in task_map
    assert (
        task_map["recap_classify"]["codex"]["model"]
        == "--model gpt-5.6-luna -c model_reasoning_effort=low"
    )
    assert (
        task_map["recap_oneshot_digest"]["codex"]["model"]
        == "--model gpt-5.6-terra -c model_reasoning_effort=low"
    )
    assert (
        task_map["recap_merge_sections"]["codex"]["model"]
        == "--model gpt-5.6-sol -c model_reasoning_effort=low"
    )
    assert task_map["recap_classify"]["claude"]["model"] == "--model haiku"
    assert (
        task_map["recap_merge_sections"]["claude"]["model"]
        == "--model claude-sonnet-5 --effort low"
    )
    assert (
        task_map["recap_classify"]["antigravity"]["model"]
        == "--model gemini-3.7-flash --effort low"
    )
    assert (
        task_map["recap_merge_sections"]["antigravity"]["model"]
        == "--model gemini-3.7-flash --effort low"
    )
    assert settings.orchestrator.api_model_map["recap_merge_sections"] == "claude-sonnet-5"
    assert settings.orchestrator.codex_command_template == (
        "codex exec --sandbox workspace-write "
        "-c sandbox_workspace_write.network_access=true "
        '{model} "Read your task from {prompt_file} and execute it."'
    )
    assert settings.orchestrator.claude_command_template == (
        "claude -p {model} --permission-mode dontAsk "
        '--allowed-tools "Read,WebFetch,'
        'Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" '
        '-- "Read your task from {prompt_file} and execute it."'
    )
    assert settings.orchestrator.antigravity_command_template == (
        "agy {model} --dangerously-skip-permissions --output-format json "
        '-p "Read your task from {prompt_file} and execute it."'
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


def test_from_env_api_backend_succeeds_without_cli_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In api mode, command templates are present but validation is skipped."""
    monkeypatch.setenv("NEWS_RECAP_EXECUTION_BACKEND", "api")
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "claude")
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


_ALL_TASK_TYPES = {
    "recap_classify",
    "recap_enrich",
    "recap_dedup",
    "recap_oneshot_digest",
    "recap_merge_sections",
    "recap_refine_layout",
}


def test_task_model_map_default_has_all_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_LLM_TASK_MODEL_MAP", raising=False)
    settings = Settings.from_env()
    assert _ALL_TASK_TYPES == set(settings.orchestrator.task_model_map.keys())


def test_api_model_map_default_has_all_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWS_RECAP_API_MODEL_MAP", raising=False)
    settings = Settings.from_env()
    assert _ALL_TASK_TYPES == set(settings.orchestrator.api_model_map.keys())


def test_task_model_map_and_api_model_map_cover_same_task_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWS_RECAP_LLM_TASK_MODEL_MAP", raising=False)
    monkeypatch.delenv("NEWS_RECAP_API_MODEL_MAP", raising=False)
    settings = Settings.from_env()
    assert set(settings.orchestrator.task_model_map.keys()) == set(
        settings.orchestrator.api_model_map.keys()
    )


def test_agent_api_key_vars_defaults() -> None:
    settings = Settings.from_env()
    key_vars = settings.orchestrator.agent_api_key_vars
    assert key_vars["claude"] == ["ANTHROPIC_API_KEY"]
    assert key_vars["codex"] == ["OPENAI_API_KEY"]
    assert key_vars["antigravity"] == ["ANTIGRAVITY_API_KEY"]


def test_routing_defaults_carries_agent_api_key_vars() -> None:
    from news_recap.recap.agents.routing import RoutingDefaults

    settings = Settings.from_env()
    rd = RoutingDefaults.from_settings(settings.orchestrator)
    assert rd.agent_api_key_vars == settings.orchestrator.agent_api_key_vars


def test_api_model_map_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEWS_RECAP_API_MODEL_MAP",
        "recap_oneshot_digest=claude-opus-5,recap_classify=claude-haiku-4-5-20251001",
    )
    settings = Settings.from_env()
    assert settings.orchestrator.api_model_map["recap_oneshot_digest"] == "claude-opus-5"
    assert settings.orchestrator.api_model_map["recap_classify"] == "claude-haiku-4-5-20251001"


@pytest.fixture()
def jev_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """Isolate the TypeSafe key lookup: empty env, cwd and data dir under *tmp_path*."""
    cwd = tmp_path / "cwd"
    data_dir = tmp_path / "data"
    cwd.mkdir()
    data_dir.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(data_dir))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("NEWS_RECAP_CLASSIFY_BACKEND", raising=False)
    return cwd, data_dir


def test_typesafe_key_lookup_precedence(
    jev_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd, data_dir = jev_env
    assert resolve_typesafe_api_key(data_dir) is None

    (data_dir / ".env").write_text("TYPESAFE_API_KEY=from-data-dir\n")
    assert resolve_typesafe_api_key(data_dir) == "from-data-dir"

    (cwd / ".env").write_text("TYPESAFE_API_KEY=from-cwd\n")
    assert resolve_typesafe_api_key(data_dir) == "from-cwd"

    monkeypatch.setenv("TYPESAFE_API_KEY", "from-env")
    assert resolve_typesafe_api_key(data_dir) == "from-env"


def test_typesafe_key_empty_value_falls_through(
    jev_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd, data_dir = jev_env
    monkeypatch.setenv("TYPESAFE_API_KEY", " ")
    (cwd / ".env").write_text("TYPESAFE_API_KEY=\nOTHER=1\n")
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=from-data-dir\n")
    assert resolve_typesafe_api_key(data_dir) == "from-data-dir"


def test_typesafe_key_from_dotenv_not_exported(jev_env: tuple[Path, Path]) -> None:
    _, data_dir = jev_env
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=from-data-dir\n")
    settings = Settings.from_env()
    assert settings.jev.api_key == "from-data-dir"
    assert "TYPESAFE_API_KEY" not in environ
    assert "from-data-dir" not in repr(settings)


def test_classify_backend_defaults_to_jev_with_key(jev_env: tuple[Path, Path]) -> None:
    _, data_dir = jev_env
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=k\n")
    assert Settings.from_env().jev.classify_backend == "jev"


def test_classify_backend_defaults_to_llm_without_key(
    jev_env: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="news_recap.config"):
        assert Settings.from_env().jev.classify_backend == "llm"
    assert not caplog.records


def test_classify_backend_llm_overrides_key(
    jev_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, data_dir = jev_env
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=k\n")
    monkeypatch.setenv("NEWS_RECAP_CLASSIFY_BACKEND", "llm")
    assert Settings.from_env().jev.classify_backend == "llm"


def test_classify_backend_jev_with_key(
    jev_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, data_dir = jev_env
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=k\n")
    monkeypatch.setenv("NEWS_RECAP_CLASSIFY_BACKEND", " JEV ")
    settings = Settings.from_env()
    assert settings.jev.classify_backend == "jev"
    assert settings.jev.model == "jev-1.13.0"


def test_classify_backend_jev_without_key_downgrades_to_llm(
    jev_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("NEWS_RECAP_CLASSIFY_BACKEND", "jev")
    with caplog.at_level("WARNING", logger="news_recap.config"):
        settings = Settings.from_env()
    assert settings.jev.classify_backend == "llm"
    assert settings.jev.api_key is None
    warnings = [r for r in caplog.records if "NEWS_RECAP_CLASSIFY_BACKEND" in r.getMessage()]
    assert len(warnings) == 1


def test_classify_backend_rejects_unknown_value(
    jev_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEWS_RECAP_CLASSIFY_BACKEND", "gemini")
    with pytest.raises(ValueError, match="NEWS_RECAP_CLASSIFY_BACKEND"):
        Settings.from_env()
