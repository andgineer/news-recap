"""Tests for UserConfigManager, build_preferences, and operation_configure."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_recap.user_config import DEFAULT_AGENT, UserConfigManager


def test_load_missing_file(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    assert mgr.load() == {}


def test_save_and_load(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    data = {"language": "en", "exclude": "sports", "follow": "tech", "default_agent": "claude"}
    mgr.save(data)

    loaded = mgr.load()
    assert loaded == data


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested"
    mgr = UserConfigManager(nested)
    mgr.save({"language": "hr"})
    assert mgr.config_path.exists()
    assert mgr.load() == {"language": "hr"}


def test_load_ignores_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"language": "en", "unknown_key": "value"}))
    mgr = UserConfigManager(tmp_path)
    assert mgr.load() == {"language": "en"}


def test_load_ignores_non_string_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"language": 42, "follow": "tech"}))
    mgr = UserConfigManager(tmp_path)
    assert mgr.load() == {"follow": "tech"}


def test_load_corrupt_json(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("not json {{{")
    mgr = UserConfigManager(tmp_path)
    assert mgr.load() == {}


def test_load_non_dict_json(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('"just a string"')
    mgr = UserConfigManager(tmp_path)
    assert mgr.load() == {}


def test_config_path(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    assert mgr.config_path == tmp_path / "config.json"


def test_build_preferences_code_defaults(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    prefs = mgr.build_preferences()
    assert prefs.language == "ru"
    assert "horoscopes" in prefs.exclude
    assert "Russia" in prefs.follow


def test_build_preferences_config_overrides(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    mgr.save({"language": "en", "exclude": "none", "follow": "AI"})
    prefs = mgr.build_preferences()
    assert prefs.language == "en"
    assert prefs.exclude == "none"
    assert prefs.follow == "AI"


def test_build_preferences_cli_overrides_config(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    mgr.save({"language": "en", "follow": "AI"})
    prefs = mgr.build_preferences(language_override="hr", follow_override="quantum")
    assert prefs.language == "hr"
    assert prefs.follow == "quantum"


def test_build_preferences_cli_overrides_code_defaults(tmp_path: Path) -> None:
    mgr = UserConfigManager(tmp_path)
    prefs = mgr.build_preferences(language_override="de")
    assert prefs.language == "de"


def test_build_preferences_partial_config(tmp_path: Path) -> None:
    """Config sets only language; other fields fall back to code defaults."""
    mgr = UserConfigManager(tmp_path)
    mgr.save({"language": "fr"})
    prefs = mgr.build_preferences()
    assert prefs.language == "fr"
    assert "horoscopes" in prefs.exclude


def test_build_preferences_empty_string_honoured(tmp_path: Path) -> None:
    """An explicit empty string in config should NOT fall through to code defaults."""
    mgr = UserConfigManager(tmp_path)
    mgr.save({"exclude": "", "follow": ""})
    prefs = mgr.build_preferences()
    assert prefs.exclude == ""
    assert prefs.follow == ""


def test_build_preferences_empty_cli_override_honoured(tmp_path: Path) -> None:
    """An explicit empty CLI override should NOT fall through to config or defaults."""
    mgr = UserConfigManager(tmp_path)
    mgr.save({"exclude": "sports"})
    prefs = mgr.build_preferences(exclude_override="")
    assert prefs.exclude == ""


def test_default_agent_constant() -> None:
    assert DEFAULT_AGENT == "codex"


# ---------------------------------------------------------------------------
# operation_configure tests
# ---------------------------------------------------------------------------


def test_configure_shows_defaults_and_skips(tmp_path: Path) -> None:
    """Enter with no selection shows current values and exits cleanly."""
    from news_recap.operation_configure import operation_configure

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path

    with (
        patch("news_recap.operation_configure.Settings.from_env", return_value=mock_settings),
        patch("news_recap.operation_configure.click.prompt", return_value=""),
    ):
        lines = list(operation_configure())

    severities = [s for s, _ in lines]
    texts = [t for _, t in lines]
    assert "heading" in severities
    assert any("Configuration" in t for t in texts)
    assert any("(default)" in t for t in texts)
    assert any("No changes" in t for t in texts)


def test_configure_updates_field(tmp_path: Path) -> None:
    """Selecting a field and providing a value saves to config."""
    from news_recap.operation_configure import operation_configure

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path

    prompt_responses = iter(["1", "en"])

    with (
        patch("news_recap.operation_configure.Settings.from_env", return_value=mock_settings),
        patch(
            "news_recap.operation_configure.click.prompt",
            side_effect=lambda *a, **kw: next(prompt_responses),
        ),
    ):
        lines = list(operation_configure())

    texts = [t for _, t in lines]
    assert any("saved" in t.lower() for t in texts)

    mgr = UserConfigManager(tmp_path)
    cfg = mgr.load()
    assert cfg["language"] == "en"


def test_configure_updates_all_fields(tmp_path: Path) -> None:
    """Selecting 'all' prompts for every field."""
    from news_recap.operation_configure import operation_configure

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path

    prompt_responses = iter(["all", "hr", "none", "AI", "gemini"])

    with (
        patch("news_recap.operation_configure.Settings.from_env", return_value=mock_settings),
        patch(
            "news_recap.operation_configure.click.prompt",
            side_effect=lambda *a, **kw: next(prompt_responses),
        ),
    ):
        lines = list(operation_configure())

    mgr = UserConfigManager(tmp_path)
    cfg = mgr.load()
    assert cfg == {"language": "hr", "exclude": "none", "follow": "AI", "default_agent": "gemini"}


def test_configure_invalid_selection_warns(tmp_path: Path) -> None:
    """Non-numeric selections produce warnings."""
    from news_recap.operation_configure import operation_configure

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path

    prompt_responses = iter(["abc"])

    with (
        patch("news_recap.operation_configure.Settings.from_env", return_value=mock_settings),
        patch(
            "news_recap.operation_configure.click.prompt",
            side_effect=lambda *a, **kw: next(prompt_responses),
        ),
    ):
        lines = list(operation_configure())

    severities = [s for s, _ in lines]
    texts = [t for _, t in lines]
    assert "warn" in severities
    assert any("No valid fields" in t for t in texts)


def test_configure_shows_config_values(tmp_path: Path) -> None:
    """When config file exists, values are shown without '(default)' suffix."""
    from news_recap.operation_configure import operation_configure

    mgr = UserConfigManager(tmp_path)
    mgr.save({"language": "hr"})

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path

    with (
        patch("news_recap.operation_configure.Settings.from_env", return_value=mock_settings),
        patch("news_recap.operation_configure.click.prompt", return_value=""),
    ):
        lines = list(operation_configure())

    texts = [t for _, t in lines]
    lang_line = next(t for t in texts if "Language:" in t)
    assert "hr" in lang_line
    assert "(default)" not in lang_line


# ---------------------------------------------------------------------------
# config.py default_agent fallback tests
# ---------------------------------------------------------------------------


def test_settings_default_agent_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var NEWS_RECAP_LLM_DEFAULT_AGENT takes priority over config file."""
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "gemini")
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(tmp_path))

    mgr = UserConfigManager(tmp_path)
    mgr.save({"default_agent": "claude"})

    from news_recap.config import Settings

    settings = Settings.from_env()
    assert settings.orchestrator.default_agent == "gemini"


def test_settings_default_agent_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config file default_agent is used when env var is not set."""
    monkeypatch.delenv("NEWS_RECAP_LLM_DEFAULT_AGENT", raising=False)
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(tmp_path))

    mgr = UserConfigManager(tmp_path)
    mgr.save({"default_agent": "claude"})

    from news_recap.config import Settings

    settings = Settings.from_env()
    assert settings.orchestrator.default_agent == "claude"


def test_settings_default_agent_code_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without env var or config file, falls back to DEFAULT_AGENT ('codex')."""
    monkeypatch.delenv("NEWS_RECAP_LLM_DEFAULT_AGENT", raising=False)
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(tmp_path))

    from news_recap.config import Settings

    settings = Settings.from_env()
    assert settings.orchestrator.default_agent == DEFAULT_AGENT
