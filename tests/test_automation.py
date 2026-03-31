from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import allure
import pytest
from click import UsageError
from click.testing import CliRunner

from news_recap.automation import (
    AutoController,
    _build_agent_args,
    _build_rss_args,
    _platform,
    _read_template,
    resolve_rss_urls,
)
from news_recap.main import news_recap

pytestmark = [
    allure.epic("Automation"),
    allure.feature("Scheduled Daily Runs"),
]


# ── _build_rss_args ───────────────────────────────────────────────────


def test_build_rss_args_single_url():
    result = _build_rss_args(("https://example.com/feed.xml",))
    assert result == "--rss 'https://example.com/feed.xml'"


def test_build_rss_args_multiple_urls():
    result = _build_rss_args(
        ("https://example.com/a.xml", "https://example.com/b.xml"),
    )
    assert "--rss 'https://example.com/a.xml'" in result
    assert "--rss 'https://example.com/b.xml'" in result


def test_build_rss_args_empty():
    assert _build_rss_args(()) == ""


# ── _build_agent_args ─────────────────────────────────────────────────


def test_build_agent_args_with_agent():
    assert _build_agent_args("claude") == "--agent claude"


def test_build_agent_args_none():
    assert _build_agent_args(None) == ""


# ── _platform ─────────────────────────────────────────────────────────


def test_platform_darwin(monkeypatch):
    monkeypatch.setattr("news_recap.automation.sys.platform", "darwin")
    assert _platform() == "macos"


def test_platform_linux(monkeypatch):
    monkeypatch.setattr("news_recap.automation.sys.platform", "linux")
    assert _platform() == "linux"


def test_platform_win32(monkeypatch):
    monkeypatch.setattr("news_recap.automation.sys.platform", "win32")
    assert _platform() == "windows"


def test_platform_unsupported(monkeypatch):
    monkeypatch.setattr("news_recap.automation.sys.platform", "freebsd")
    with pytest.raises(RuntimeError, match="Unsupported"):
        _platform()


# ── _read_template ────────────────────────────────────────────────────


def test_read_template_macos():
    content = _read_template("macos_run.sh")
    assert "{{RSS_ARGS}}" in content
    assert "{{AGENT_ARGS}}" in content
    assert "news-recap ingest" in content
    assert "RESULT: OK" in content
    assert "RESULT: FAILED" in content


def test_read_template_linux():
    content = _read_template("linux_run.sh")
    assert "{{RSS_ARGS}}" in content
    assert "{{AGENT_ARGS}}" in content
    assert "news-recap recap" in content
    assert "RESULT: OK" in content
    assert "RESULT: FAILED" in content


def test_read_template_windows():
    content = _read_template("windows_run.ps1")
    assert "{{RSS_ARGS}}" in content
    assert "{{AGENT_ARGS}}" in content
    assert "news-recap ingest" in content
    assert "RESULT: OK" in content
    assert "RESULT: FAILED" in content


# ── _resolve_rss_urls ─────────────────────────────────────────────────


def test_resolve_rss_urls_from_cli():
    urls = resolve_rss_urls(("https://a.com/rss", "https://b.com/rss"))
    assert urls == ("https://a.com/rss", "https://b.com/rss")


def test_resolve_rss_urls_from_env(monkeypatch):
    monkeypatch.setenv("NEWS_RECAP_RSS_FEED_URLS", "https://a.com/rss,https://b.com/rss")
    urls = resolve_rss_urls(())
    assert urls == ("https://a.com/rss", "https://b.com/rss")


def test_resolve_rss_urls_cli_takes_precedence(monkeypatch):
    monkeypatch.setenv("NEWS_RECAP_RSS_FEED_URLS", "https://env.com/rss")
    urls = resolve_rss_urls(("https://cli.com/rss",))
    assert urls == ("https://cli.com/rss",)


def test_resolve_rss_urls_error_when_empty(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)
    with pytest.raises(UsageError, match="--rss"):
        resolve_rss_urls(())


def test_resolve_rss_urls_env_whitespace_only(monkeypatch):
    monkeypatch.setenv("NEWS_RECAP_RSS_FEED_URLS", "  ,  , ")
    with pytest.raises(UsageError, match="--rss"):
        resolve_rss_urls(())


# ── CLI smoke tests ───────────────────────────────────────────────────


def test_auto_cli_help():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["auto", "--help"])
    assert result.exit_code == 0
    assert "--rss" in result.output
    assert "--agent" in result.output
    assert "daily" in result.output.lower() or "automation" in result.output.lower()


def test_auto_off_cli_help():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["auto-off", "--help"])
    assert result.exit_code == 0


def test_auto_cli_requires_rss(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["auto"])
    assert result.exit_code != 0
    assert "--rss" in result.output


def test_auto_cli_with_rss_from_env(monkeypatch):
    monkeypatch.setenv("NEWS_RECAP_RSS_FEED_URLS", "https://example.com/feed.xml")

    calls: list[tuple] = []

    def fake_install(self, rss_urls, agent=None):
        calls.append((rss_urls, agent))
        yield ("ok", "OK")

    monkeypatch.setattr(AutoController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["auto"])
    assert result.exit_code == 0
    assert calls == [(("https://example.com/feed.xml",), None)]


def test_auto_cli_with_rss_option(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)

    calls: list[tuple] = []

    def fake_install(self, rss_urls, agent=None):
        calls.append((rss_urls, agent))
        yield ("ok", "OK")

    monkeypatch.setattr(AutoController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["auto", "--rss", "https://a.com/rss", "--rss", "https://b.com/rss"],
    )
    assert result.exit_code == 0
    assert calls == [(("https://a.com/rss", "https://b.com/rss"), None)]


def test_auto_cli_with_agent_option(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)

    calls: list[tuple] = []

    def fake_install(self, rss_urls, agent=None):
        calls.append((rss_urls, agent))
        yield ("ok", "OK")

    monkeypatch.setattr(AutoController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["auto", "--rss", "https://a.com/rss", "--agent", "gemini"],
    )
    assert result.exit_code == 0
    assert calls == [(("https://a.com/rss",), "gemini")]


def test_auto_off_cli_delegates(monkeypatch):
    calls = []

    def fake_uninstall(self):
        calls.append(True)
        yield ("ok", "Removed")

    monkeypatch.setattr(AutoController, "uninstall", fake_uninstall)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["auto-off"])
    assert result.exit_code == 0
    assert calls == [True]
    assert "Removed" in result.output


# ── macOS install ─────────────────────────────────────────────────────


def test_install_macos_creates_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        ctrl = AutoController()
        output = list(ctrl.install(("https://example.com/feed.xml",), agent="claude"))

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    assert run_script.exists()
    content = run_script.read_text()
    assert "--rss 'https://example.com/feed.xml'" in content
    assert "--agent claude" in content
    assert "{{RSS_ARGS}}" not in content
    assert "{{AGENT_ARGS}}" not in content
    assert run_script.stat().st_mode & stat.S_IXUSR

    plist = tmp_path / "Library" / "LaunchAgents" / "com.news-recap.daily.plist"
    assert plist.exists()
    plist_text = plist.read_text()
    assert "com.news-recap.daily" in plist_text
    assert str(run_script) in plist_text

    texts = [t for _, t in output]
    assert any("LaunchAgent" in t for t in texts)
    assert any("test run" in t.lower() for t in texts)
    assert mock_run.call_count == 3  # unload + load + start


def test_install_macos_no_agent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run"):
        ctrl = AutoController()
        list(ctrl.install(("https://example.com/feed.xml",)))

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    content = run_script.read_text()
    assert "--agent" not in content
    assert "{{AGENT_ARGS}}" not in content


def test_install_macos_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run"):
        ctrl = AutoController()
        list(ctrl.install(("https://feed1.com/rss",)))
        list(ctrl.install(("https://feed2.com/rss",)))

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    content = run_script.read_text()
    assert "feed2.com" in content
    assert "feed1.com" not in content


# ── macOS uninstall ───────────────────────────────────────────────────


def test_uninstall_macos_removes_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    plist = tmp_path / "Library" / "LaunchAgents" / "com.news-recap.daily.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist/>")

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    run_script.parent.mkdir(parents=True)
    run_script.write_text("#!/bin/bash")

    with patch("news_recap.automation.subprocess.run"):
        ctrl = AutoController()
        output = list(ctrl.uninstall())

    assert not plist.exists()
    assert not run_script.exists()
    assert any("Removed" in t for _, t in output)


def test_uninstall_macos_not_installed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    ctrl = AutoController()
    output = list(ctrl.uninstall())
    assert any("Not installed" in t for _, t in output)


# ── Linux install ─────────────────────────────────────────────────────


def test_install_linux_creates_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")
    monkeypatch.setattr("news_recap.automation.shutil.which", lambda cmd: "/usr/bin/systemctl")

    with patch("news_recap.automation.subprocess.run"):
        ctrl = AutoController()
        output = list(ctrl.install(("https://example.com/feed.xml",), agent="gemini"))

    run_script = tmp_path / ".local" / "share" / "news-recap" / "run.sh"
    assert run_script.exists()
    content = run_script.read_text()
    assert "--rss 'https://example.com/feed.xml'" in content
    assert "--agent gemini" in content
    assert "{{AGENT_ARGS}}" not in content
    assert run_script.stat().st_mode & stat.S_IXUSR

    service = tmp_path / ".config" / "systemd" / "user" / "news-recap.service"
    assert service.exists()
    assert str(run_script) in service.read_text()

    timer = tmp_path / ".config" / "systemd" / "user" / "news-recap.timer"
    assert timer.exists()
    assert "03:00:00" in timer.read_text()

    assert any("Installed" in t for _, t in output)


def test_install_linux_requires_systemctl(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")
    monkeypatch.setattr("news_recap.automation.shutil.which", lambda cmd: None)

    ctrl = AutoController()
    with pytest.raises(RuntimeError, match="systemctl"):
        list(ctrl.install(("https://example.com/feed.xml",)))


# ── Linux uninstall ───────────────────────────────────────────────────


def test_uninstall_linux_removes_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")

    systemd_dir = tmp_path / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True)
    (systemd_dir / "news-recap.timer").write_text("[Timer]")
    (systemd_dir / "news-recap.service").write_text("[Service]")

    run_script = tmp_path / ".local" / "share" / "news-recap" / "run.sh"
    run_script.parent.mkdir(parents=True)
    run_script.write_text("#!/bin/bash")

    with patch("news_recap.automation.subprocess.run"):
        ctrl = AutoController()
        output = list(ctrl.uninstall())

    assert not (systemd_dir / "news-recap.timer").exists()
    assert not (systemd_dir / "news-recap.service").exists()
    assert not run_script.exists()
    assert any("Removed" in t for _, t in output)


def test_uninstall_linux_not_installed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")

    ctrl = AutoController()
    output = list(ctrl.uninstall())
    assert any("Not installed" in t for _, t in output)


# ── Windows install ───────────────────────────────────────────────────


def test_install_windows_creates_script(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    with patch("news_recap.automation.subprocess.run"):
        ctrl = AutoController()
        output = list(ctrl.install(("https://example.com/feed.xml",), agent="claude"))

    run_script = tmp_path / "AppData" / "Local" / "news-recap" / "run.ps1"
    assert run_script.exists()
    content = run_script.read_text()
    assert "--rss 'https://example.com/feed.xml'" in content
    assert "--agent claude" in content
    assert "{{AGENT_ARGS}}" not in content
    assert any("scheduled task" in t.lower() for _, t in output)


# ── Windows uninstall ─────────────────────────────────────────────────


def test_uninstall_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    run_script = tmp_path / "AppData" / "Local" / "news-recap" / "run.ps1"
    run_script.parent.mkdir(parents=True)
    run_script.write_text("script")

    mock_result = type("R", (), {"returncode": 0})()
    with patch("news_recap.automation.subprocess.run", return_value=mock_result):
        ctrl = AutoController()
        output = list(ctrl.uninstall())

    assert not run_script.exists()
    assert any("Removed" in t for _, t in output)
