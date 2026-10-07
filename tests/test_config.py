from __future__ import annotations

from os import environ
from pathlib import Path

import allure
import pytest

from news_recap.config import (
    IngestionSettings,
    OrchestratorSettings,
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

    with pytest.raises(ValueError, match="config set rss"):
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
        rss=RssSettings(feed_urls=("https://example.com/feed.xml",), default_items_per_feed=0),
    )
    with pytest.raises(ValueError, match="default_items_per_feed"):
        settings.validate_for_rss()


def test_validate_for_rss_rejects_non_positive_per_feed_override() -> None:
    settings = Settings(
        rss=RssSettings(
            feed_urls=("https://example.com/feed.xml",),
            per_feed_items={"https://example.com/feed.xml": -1},
        ),
    )
    with pytest.raises(ValueError, match="fetch.per_feed_items must be positive"):
        settings.validate_for_rss()


# ---------------------------------------------------------------------------
# Defaults (no config.toml)
# ---------------------------------------------------------------------------


def test_defaults_without_a_config_file() -> None:
    settings = Settings.load()
    assert settings.data_dir == Path(environ["NEWS_RECAP_DATA_DIR"])
    assert settings.orchestrator.workdir_root == settings.data_dir / "workdir"
    assert settings.orchestrator.default_agent == "antigravity"
    assert settings.orchestrator.execution_backend == "cli"
    assert settings.ingestion.digest_lookback_days == 2
    assert settings.ingestion.gc_retention_days == 7
    assert settings.rss.feed_urls == ()
    assert (settings.jev.classify_backend, settings.jev.dedup_backend) == ("llm", "llm")
    assert settings.preferences.language == "ru"
    assert not (settings.data_dir / "config.toml").exists()  # loading never writes


def test_default_model_maps_and_command_templates() -> None:
    orch = Settings.load().orchestrator
    task_map = orch.task_model_map
    assert (
        set(task_map)
        == set(orch.api_model_map)
        == {
            "recap_classify",
            "recap_enrich",
            "recap_dedup",
            "recap_oneshot_digest",
            "recap_merge_sections",
            "recap_refine_layout",
        }
    )
    assert task_map["recap_classify"]["codex"]["model"] == (
        "--model gpt-5.6-luna -c model_reasoning_effort=low"
    )
    assert task_map["recap_merge_sections"]["claude"]["model"] == (
        "--model claude-sonnet-5 --effort low"
    )
    assert task_map["recap_classify"]["antigravity"]["model"] == (
        "--model gemini-3.7-flash --effort low"
    )
    assert orch.api_model_map["recap_merge_sections"] == "claude-sonnet-5"
    assert orch.antigravity_command_template == (
        "agy {model} --dangerously-skip-permissions --output-format json "
        '-p "Read your task from {prompt_file} and execute it."'
    )
    assert orch.agent_api_key_vars["claude"] == ["ANTHROPIC_API_KEY"]
    assert (orch.api_max_parallel, orch.api_concurrency_recovery_successes) == (5, 10)
    assert (orch.api_retry_max_backoff_seconds, orch.api_retry_jitter_seconds) == (60.0, 5.0)
    assert orch.api_downshift_pause_seconds == 2.0


def test_routing_defaults_carries_agent_api_key_vars() -> None:
    from news_recap.recap.agents.routing import RoutingDefaults

    settings = Settings.load()
    rd = RoutingDefaults.from_settings(settings.orchestrator)
    assert rd.agent_api_key_vars == settings.orchestrator.agent_api_key_vars


# ---------------------------------------------------------------------------
# Values from config.toml
# ---------------------------------------------------------------------------


def test_everyday_keys_come_from_the_file(write_config) -> None:
    write_config(
        'language = "en"\n'
        'exclude = """\nhoroscopes\nsports (except Russia)\n"""\n'
        'follow = """\nSerbia\n"""\n'
        'agent = "claude"\n'
        'rss = ["https://a.example/feed.xml", " https://a.example/feed.xml "]\n',
    )
    settings = Settings.load()
    assert settings.preferences.language == "en"
    assert settings.preferences.exclude == "horoscopes\nsports (except Russia)"
    assert settings.preferences.follow == "Serbia"
    assert settings.orchestrator.default_agent == "claude"
    assert settings.rss.feed_urls == ("https://a.example/feed.xml",)


def test_advanced_sections_come_from_the_file(write_config) -> None:
    write_config(
        "[ingestion]\nlookback_days = 5\nretention_days = 14\n"
        '[fetch]\nper_feed_items = { "https://a.example/feed.xml" = 123 }\n'
        "request_timeout_seconds = 10\n"
        "[dedup]\nthreshold = 0.85\n"
        '[llm]\nworkdir_root = "~/wd"\n'
        'models.recap_classify.claude = "--model sonnet"\n'
        '[api]\nmodel_map.recap_oneshot_digest = "claude-opus-5"\nmax_parallel = 2\n',
    )
    settings = Settings.load()
    assert settings.ingestion.digest_lookback_days == 5
    assert settings.ingestion.gc_retention_days == 14
    assert settings.rss.per_feed_items == {"https://a.example/feed.xml": 123}
    assert settings.rss.request_timeout_seconds == 10.0
    assert settings.dedup.threshold == 0.85
    assert settings.orchestrator.workdir_root == Path("~/wd").expanduser()
    classify = settings.orchestrator.task_model_map["recap_classify"]
    assert classify["claude"] == {"model": "--model sonnet", "env": {"MAX_THINKING_TOKENS": "0"}}
    assert classify["codex"]["model"] == "--model gpt-5.6-luna -c model_reasoning_effort=low"
    assert settings.orchestrator.api_model_map["recap_oneshot_digest"] == "claude-opus-5"
    assert settings.orchestrator.api_model_map["recap_classify"] == "claude-haiku-4-5-20251001"
    assert settings.orchestrator.api_max_parallel == 2


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("langauge = 'en'\n", "unknown key langauge"),
        ("[ingestion]\nlookback = 3\n", "unknown key ingestion.lookback"),
        ("[ingestion]\nlookback_days = '3'\n", "ingestion.lookback_days must be an integer"),
        ("[ingestion]\nlookback_days = true\n", "ingestion.lookback_days must be an integer"),
        ("rss = 'https://a.example/feed.xml'\n", "rss must be a list"),
        ("agent = 'gemini'\n", "agent must be one of antigravity | codex | claude"),
        ("classify_backend = 'jev2'\n", "classify_backend must be one of llm | jev"),
        ("ingestion = 3\n", r"\[ingestion\] must be a table"),
        ("[llm]\nmodels.recap_classify = 'x'\n", "llm.models: expected task.agent"),
        ("[api]\nmodel_map.recap_classify = 1\n", "api.model_map: expected task"),
        ("[fetch]\nper_feed_items = { 'https://a' = 'x' }\n", "fetch.per_feed_items: expected"),
        ("language = \n", "config.toml"),
    ],
)
def test_bad_config_names_the_key_and_the_file(write_config, text: str, match: str) -> None:
    path = write_config(text)
    with pytest.raises(ValueError, match=match) as raised:
        Settings.load()
    assert str(path) in str(raised.value)


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("[ingestion]\nretention_days = 0\n", "ingestion.retention_days"),
        ("[ingestion]\nlookback_days = 0\n", "ingestion.lookback_days"),
        ("[dedup]\nthreshold = 1.5\n", "dedup.threshold"),
        ("[api]\nmax_parallel = 0\n", "api.max_parallel"),
        ("[api]\nconcurrency_recovery_successes = 0\n", "api.concurrency_recovery_successes"),
        ("[api]\nretry_max_backoff_seconds = -1\n", "api.retry_max_backoff_seconds"),
        ("[api]\nretry_jitter_seconds = -1\n", "api.retry_jitter_seconds"),
        ("[api]\ndownshift_pause_seconds = -1\n", "api.downshift_pause_seconds"),
    ],
)
def test_out_of_range_values_are_rejected(write_config, text: str, match: str) -> None:
    write_config(text)
    with pytest.raises(ValueError, match=match):
        Settings.load()


def test_validate_rejects_zero_gc_retention_days() -> None:
    settings = Settings(ingestion=IngestionSettings(gc_retention_days=0))
    with pytest.raises(ValueError, match="retention_days"):
        settings.validate()


# ---------------------------------------------------------------------------
# API backend
# ---------------------------------------------------------------------------


def test_api_backend_requires_the_claude_agent(write_config) -> None:
    write_config('agent = "codex"\n[llm]\nexecution_backend = "api"\n')
    with pytest.raises(ValueError) as exc_info:
        Settings.load()
    msg = str(exc_info.value)
    assert "requires the claude agent" in msg
    assert 'agent = "claude"' in msg
    assert "codex" in msg


def test_api_backend_with_the_claude_agent(write_config) -> None:
    write_config('agent = "claude"\n[llm]\nexecution_backend = "api"\n')
    settings = Settings.load()
    assert settings.orchestrator.execution_backend == "api"
    assert settings.orchestrator.default_agent == "claude"


def test_api_override_forces_the_claude_agent() -> None:
    settings = Settings.load(execution_backend="api")
    assert settings.orchestrator.execution_backend == "api"
    assert settings.orchestrator.default_agent == "claude"


def test_validate_rejects_invalid_execution_backend() -> None:
    settings = Settings(orchestrator=OrchestratorSettings(execution_backend="grpc"))
    with pytest.raises(ValueError, match="execution_backend"):
        settings.validate()


# ---------------------------------------------------------------------------
# Jev: the key from the environment or .env, the backends from config.toml
# ---------------------------------------------------------------------------


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
    settings = Settings.load()
    assert settings.jev.api_key == "from-data-dir"
    assert "TYPESAFE_API_KEY" not in environ
    assert "from-data-dir" not in repr(settings)


def test_backends_stay_on_the_llm_with_a_key(jev_env: tuple[Path, Path]) -> None:
    _, data_dir = jev_env
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=k\n")
    settings = Settings.load()
    assert (settings.jev.classify_backend, settings.jev.dedup_backend) == ("llm", "llm")


def test_backends_from_the_file_with_a_key(jev_env: tuple[Path, Path]) -> None:
    _, data_dir = jev_env
    (data_dir / ".env").write_text("TYPESAFE_API_KEY=k\n")
    (data_dir / "config.toml").write_text('classify_backend = "jev"\ndedup_backend = "llm"\n')
    settings = Settings.load()
    assert (settings.jev.classify_backend, settings.jev.dedup_backend) == ("jev", "llm")
    assert settings.jev.model == "jev-1.13.0"


def test_jev_without_a_key_falls_back_to_the_llm(
    jev_env: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    _, data_dir = jev_env
    (data_dir / "config.toml").write_text('classify_backend = "jev"\ndedup_backend = "jev"\n')
    with caplog.at_level("WARNING", logger="news_recap.config"):
        settings = Settings.load()
    assert (settings.jev.classify_backend, settings.jev.dedup_backend) == ("llm", "llm")
    assert settings.jev.api_key is None
    messages = [r.getMessage() for r in caplog.records]
    assert any("classify_backend" in m and "TYPESAFE_API_KEY" in m for m in messages)
    assert any("dedup_backend" in m for m in messages)
