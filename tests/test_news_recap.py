import allure
from click.testing import CliRunner
from pathlib import Path
from unittest.mock import MagicMock, patch

from news_recap import __version__
from news_recap.main import news_recap

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Routing, Failures, CLI Ops"),
]


def test_version():
    assert __version__


def test_version_option():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_all_commands():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--help"])
    assert result.exit_code == 0
    for cmd in ("ingest", "create", "prompt", "info", "list", "delete", "serve", "schedule"):
        assert cmd in result.output, f"command {cmd!r} missing from --help output"


def test_info_shows_app_paths():
    runner = CliRunner()
    settings = MagicMock()
    data_dir = Path("/tmp/news-data").resolve()
    workdir_root = Path("/tmp/news-workdir").resolve()
    app_dir = Path("/tmp/news-app").resolve()
    log_dir = Path("/tmp/news-logs").resolve()
    settings.data_dir = data_dir
    settings.orchestrator.workdir_root = workdir_root

    with (
        patch("news_recap.main.Settings.from_env", return_value=settings),
        patch("news_recap.main._platform", return_value="linux"),
        patch("news_recap.main._app_dir", return_value=app_dir),
        patch("news_recap.main._log_dir", return_value=log_dir),
    ):
        result = runner.invoke(news_recap, ["info"])

    assert result.exit_code == 0
    assert "App paths:" in result.output
    assert f"DB / data dir: {data_dir}" in result.output
    assert f"Feed cache: {data_dir / 'feeds.json'}" in result.output
    assert f"Run history: {data_dir / 'runs.json'}" in result.output
    assert f"Resource cache: {data_dir / 'resources'}" in result.output
    assert f"Digest workdir: {workdir_root}" in result.output
    assert f"App dir: {app_dir}" in result.output
    assert f"Schedule metadata: {app_dir / 'schedule.json'}" in result.output
    assert f"Logs: {log_dir}" in result.output
