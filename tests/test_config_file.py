"""config.toml: the generated template, ``config set`` and the ``config`` command."""

from __future__ import annotations

import tomllib
from os import environ
from pathlib import Path

import pytest
from click.testing import CliRunner

from news_recap.config import Settings
from news_recap.config_file import (
    SECTIONS,
    TOP_LEVEL,
    load_config_file,
    render_template,
    set_config_value,
)
from news_recap.main import news_recap
from news_recap.recap.jev.policy import split_policy_topics


def _data_dir() -> Path:
    return Path(environ["NEWS_RECAP_DATA_DIR"])


def _defaults() -> Settings:
    return Settings.defaults(_data_dir())


def test_template_sets_the_everyday_keys_and_comments_out_the_rest(tmp_path: Path) -> None:
    text = render_template(_defaults())
    path = tmp_path / "config.toml"
    path.write_text(text, "utf-8")

    parsed = tomllib.loads(text)
    assert set(parsed) == {k.name for k in TOP_LEVEL} | set(SECTIONS)
    assert all(parsed[section] == {} for section in SECTIONS)  # advanced keys commented out
    for section, keys in SECTIONS.items():
        for key in keys:
            assert f"# {key.name}" in text, f"{section}.{key.name} missing from the template"
    assert 'exclude = """\nhoroscopes\nmedical advice\n' in text
    assert "antigravity (free Gemini tier, no keys) | codex | claude" in text
    assert "# classify_backend" not in text and "llm | jev" in text

    values = {key.name: value for key, value in load_config_file(path)}
    preferences = _defaults().preferences
    assert split_policy_topics(values["exclude"]) == split_policy_topics(preferences.exclude)
    assert split_policy_topics(values["follow"]) == split_policy_topics(preferences.follow)


def test_template_file_loads_to_the_release_defaults(write_config) -> None:
    write_config(render_template(_defaults()))
    loaded = Settings.load()
    defaults = Settings.defaults(loaded.data_dir)
    assert loaded.ingestion == defaults.ingestion
    assert loaded.dedup == defaults.dedup
    assert loaded.orchestrator.task_model_map == defaults.orchestrator.task_model_map
    assert loaded.orchestrator.default_agent == "antigravity"
    assert loaded.preferences.language == defaults.preferences.language


def test_set_keeps_comments_and_writes_topics_one_per_line(write_config) -> None:
    path = write_config(render_template(_defaults()))
    with path.open("a", encoding="utf-8") as f:
        f.write("# my own note\n")

    set_config_value(path, _defaults(), "exclude", ["horoscopes", "  ", "sports (except Russia)"])
    set_config_value(path, _defaults(), "rss", ["https://a.example/rss", "https://b.example/rss"])
    set_config_value(path, _defaults(), "classify_backend", ["jev"])

    text = path.read_text("utf-8")
    assert "# my own note" in text
    assert "# lookback_days = 2" in text
    assert 'exclude = """\nhoroscopes\nsports (except Russia)\n"""' in text
    settings = Settings.load()
    assert settings.preferences.exclude == "horoscopes\nsports (except Russia)"
    assert settings.rss.feed_urls == ("https://a.example/rss", "https://b.example/rss")


def test_set_creates_the_file_from_the_template() -> None:
    path = _data_dir() / "config.toml"
    set_config_value(path, _defaults(), "language", ["en"])
    text = path.read_text("utf-8")
    assert 'language = "en"' in text
    assert "[ingestion]" in text


@pytest.mark.parametrize(
    ("name", "values", "match"),
    [
        ("lookback_days", ["3"], "unknown key 'lookback_days'"),
        ("agent", ["gemini"], "agent must be one of antigravity | codex | claude"),
        ("dedup_backend", ["yes"], "dedup_backend must be one of llm | jev"),
        ("rss", ["ftp://a.example/rss"], "not an http"),
        ("language", ["en", "ru"], "takes one value"),
        ("language", [], "needs a value"),
    ],
)
def test_set_rejects_bad_input(name: str, values: list[str], match: str) -> None:
    path = _data_dir() / "config.toml"
    with pytest.raises(ValueError, match=match):
        set_config_value(path, _defaults(), name, values)
    assert not path.exists()


def test_config_command_creates_and_shows_the_file() -> None:
    result = CliRunner().invoke(news_recap, ["--no-color", "config"])

    assert result.exit_code == 0, result.output
    path = _data_dir() / "config.toml"
    assert path.exists()
    assert f"Created {path}" in result.output
    assert "agent = antigravity" in result.output
    assert "    horoscopes" in result.output
    assert "rss: (none)" in result.output

    again = CliRunner().invoke(news_recap, ["--no-color", "config"])
    assert "Created" not in again.output


def test_config_set_command() -> None:
    runner = CliRunner()
    result = runner.invoke(
        news_recap, ["--no-color", "config", "set", "rss", "https://a.example/rss"]
    )
    assert result.exit_code == 0, result.output
    assert "https://a.example/rss" in result.output
    assert Settings.load().rss.feed_urls == ("https://a.example/rss",)

    bad = runner.invoke(news_recap, ["--no-color", "config", "set", "agent", "gemini"])
    assert bad.exit_code != 0
    assert "agent must be one of" in bad.output


def test_config_command_reports_a_broken_file(write_config) -> None:
    write_config("langauge = 'en'\n")
    result = CliRunner().invoke(news_recap, ["--no-color", "config"])
    assert result.exit_code != 0
    assert "unknown key langauge" in result.output
