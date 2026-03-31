from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import allure
import pytest
from click import UsageError
from click.testing import CliRunner

from news_recap.automation import (
    ScheduleController,
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

_MOCK_CP = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


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
    assert "{{NEWS_RECAP_CMD}}" in content
    assert "create" in content
    assert "RESULT: OK" in content
    assert "RESULT: FAILED" in content


def test_read_template_linux():
    content = _read_template("linux_run.sh")
    assert "{{RSS_ARGS}}" in content
    assert "{{AGENT_ARGS}}" in content
    assert "{{NEWS_RECAP_CMD}}" in content
    assert "create" in content
    assert "RESULT: OK" in content
    assert "RESULT: FAILED" in content


def test_read_template_windows():
    content = _read_template("windows_run.ps1")
    assert "{{RSS_ARGS}}" in content
    assert "{{AGENT_ARGS}}" in content
    assert "{{NEWS_RECAP_CMD}}" in content
    assert "create" in content
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


def test_schedule_set_cli_help():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "set", "--help"])
    assert result.exit_code == 0
    assert "--rss" in result.output
    assert "--agent" in result.output
    assert "--time" in result.output
    assert "--venv" in result.output


def test_schedule_get_cli_help():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "get", "--help"])
    assert result.exit_code == 0


def test_schedule_delete_cli_help():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "delete", "--help"])
    assert result.exit_code == 0


def test_schedule_set_requires_rss(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "set"])
    assert result.exit_code != 0
    assert "--rss" in result.output


def test_schedule_set_with_rss_from_env(monkeypatch):
    monkeypatch.setenv("NEWS_RECAP_RSS_FEED_URLS", "https://example.com/feed.xml")

    calls: list[dict] = []

    def fake_install(self, rss_urls, agent=None, *, hour=3, minute=0, venv_bin=None):
        calls.append(
            {
                "rss_urls": rss_urls,
                "agent": agent,
                "hour": hour,
                "minute": minute,
                "venv_bin": venv_bin,
            }
        )
        yield ("ok", "OK")

    monkeypatch.setattr(ScheduleController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "set"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["rss_urls"] == ("https://example.com/feed.xml",)
    assert calls[0]["hour"] == 3
    assert calls[0]["minute"] == 0
    assert calls[0]["venv_bin"] is None


def test_schedule_set_with_rss_option(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)

    calls: list[dict] = []

    def fake_install(self, rss_urls, agent=None, *, hour=3, minute=0, venv_bin=None):
        calls.append({"rss_urls": rss_urls, "agent": agent})
        yield ("ok", "OK")

    monkeypatch.setattr(ScheduleController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["schedule", "set", "--rss", "https://a.com/rss", "--rss", "https://b.com/rss"],
    )
    assert result.exit_code == 0
    assert calls[0]["rss_urls"] == ("https://a.com/rss", "https://b.com/rss")


def test_schedule_set_with_agent_option(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)

    calls: list[dict] = []

    def fake_install(self, rss_urls, agent=None, *, hour=3, minute=0, venv_bin=None):
        calls.append({"rss_urls": rss_urls, "agent": agent})
        yield ("ok", "OK")

    monkeypatch.setattr(ScheduleController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["schedule", "set", "--rss", "https://a.com/rss", "--agent", "gemini"],
    )
    assert result.exit_code == 0
    assert calls[0]["agent"] == "gemini"


def test_schedule_set_with_time_option(monkeypatch):
    monkeypatch.delenv("NEWS_RECAP_RSS_FEED_URLS", raising=False)

    calls: list[dict] = []

    def fake_install(self, rss_urls, agent=None, *, hour=3, minute=0, venv_bin=None):
        calls.append({"hour": hour, "minute": minute})
        yield ("ok", "OK")

    monkeypatch.setattr(ScheduleController, "install", fake_install)
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["schedule", "set", "--rss", "https://a.com/rss", "--time", "07:30"],
    )
    assert result.exit_code == 0
    assert calls[0] == {"hour": 7, "minute": 30}


def test_schedule_set_invalid_time():
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["schedule", "set", "--rss", "https://a.com/rss", "--time", "25:00"],
    )
    assert result.exit_code != 0


def test_schedule_set_bad_time_format():
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["schedule", "set", "--rss", "https://a.com/rss", "--time", "3pm"],
    )
    assert result.exit_code != 0


def test_schedule_get_cli_delegates(monkeypatch):
    calls = []

    def fake_get_schedule(self):
        calls.append(True)
        yield ("heading", "Current schedule:")
        yield ("info", "  Time: 07:30")

    monkeypatch.setattr(ScheduleController, "get_schedule", fake_get_schedule)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "get"])
    assert result.exit_code == 0
    assert calls == [True]
    assert "07:30" in result.output


def test_schedule_delete_cli_delegates(monkeypatch):
    calls = []

    def fake_uninstall(self):
        calls.append(True)
        yield ("ok", "Removed")

    monkeypatch.setattr(ScheduleController, "uninstall", fake_uninstall)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["schedule", "delete"])
    assert result.exit_code == 0
    assert calls == [True]
    assert "Removed" in result.output


# ── macOS install ─────────────────────────────────────────────────────


def test_install_macos_creates_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP) as mock_run:
        ctrl = ScheduleController()
        output = list(ctrl.install(("https://example.com/feed.xml",), agent="claude"))

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    assert run_script.exists()
    content = run_script.read_text()
    assert "--rss 'https://example.com/feed.xml'" in content
    assert "--agent claude" in content
    assert "{{RSS_ARGS}}" not in content
    assert "{{AGENT_ARGS}}" not in content
    assert "{{NEWS_RECAP_CMD}}" not in content
    if sys.platform != "win32":
        assert run_script.stat().st_mode & stat.S_IXUSR

    plist = tmp_path / "Library" / "LaunchAgents" / "com.news-recap.daily.plist"
    assert plist.exists()
    plist_text = plist.read_text()
    assert "com.news-recap.daily" in plist_text
    assert str(run_script) in plist_text

    texts = [t for _, t in output]
    assert any("LaunchAgent" in t for t in texts)
    assert any("verifying" in t.lower() for t in texts)
    assert mock_run.call_count == 4  # unload + load + ingest smoke + create smoke

    meta_file = tmp_path / "Library" / "Application Support" / "news-recap" / "schedule.json"
    assert meta_file.exists()
    meta = json.loads(meta_file.read_text())
    assert meta["time"] == "03:00"
    assert meta["agent"] == "claude"


def test_install_macos_custom_time(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        list(
            ctrl.install(
                ("https://example.com/feed.xml",),
                hour=7,
                minute=30,
            )
        )

    plist = tmp_path / "Library" / "LaunchAgents" / "com.news-recap.daily.plist"
    plist_text = plist.read_text()
    assert "<integer>7</integer>" in plist_text
    assert "<integer>30</integer>" in plist_text

    meta_file = tmp_path / "Library" / "Application Support" / "news-recap" / "schedule.json"
    meta = json.loads(meta_file.read_text())
    assert meta["time"] == "07:30"


def test_install_macos_venv_bin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        list(
            ctrl.install(
                ("https://example.com/feed.xml",),
                venv_bin="/my/venv/bin/news-recap",
            )
        )

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    content = run_script.read_text()
    assert "/my/venv/bin/news-recap" in content
    assert "{{NEWS_RECAP_CMD}}" not in content

    meta_file = tmp_path / "Library" / "Application Support" / "news-recap" / "schedule.json"
    meta = json.loads(meta_file.read_text())
    assert meta["venv"] is True
    assert meta["venv_bin"] == "/my/venv/bin/news-recap"


def test_install_macos_no_agent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        list(ctrl.install(("https://example.com/feed.xml",)))

    run_script = tmp_path / "Library" / "Application Support" / "news-recap" / "run.sh"
    content = run_script.read_text()
    assert "--agent" not in content
    assert "{{AGENT_ARGS}}" not in content


def test_install_macos_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
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

    app_dir = tmp_path / "Library" / "Application Support" / "news-recap"
    run_script = app_dir / "run.sh"
    run_script.parent.mkdir(parents=True)
    run_script.write_text("#!/bin/bash")
    (app_dir / "schedule.json").write_text("{}")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        output = list(ctrl.uninstall())

    assert not plist.exists()
    assert not run_script.exists()
    assert not (app_dir / "schedule.json").exists()
    assert any("Removed" in t for _, t in output)


def test_uninstall_macos_not_installed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    ctrl = ScheduleController()
    output = list(ctrl.uninstall())
    assert any("Not installed" in t for _, t in output)


# ── schedule get ──────────────────────────────────────────────────────


def test_get_schedule_no_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    ctrl = ScheduleController()
    output = list(ctrl.get_schedule())
    assert any("No schedule configured" in t for _, t in output)


def test_get_schedule_shows_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "macos")

    app_dir = tmp_path / "Library" / "Application Support" / "news-recap"
    app_dir.mkdir(parents=True)
    meta = {
        "time": "07:30",
        "venv": True,
        "venv_bin": "/my/venv/bin/news-recap",
        "rss_urls": ["https://a.com/rss"],
        "agent": "claude",
    }
    (app_dir / "schedule.json").write_text(json.dumps(meta))

    ctrl = ScheduleController()
    output = list(ctrl.get_schedule())
    texts = [t for _, t in output]
    assert any("07:30" in t for t in texts)
    assert any("claude" in t for t in texts)
    assert any("/my/venv/bin/news-recap" in t for t in texts)
    assert any("https://a.com/rss" in t for t in texts)


# ── Linux install ─────────────────────────────────────────────────────


def test_install_linux_creates_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")
    monkeypatch.setattr("news_recap.automation.shutil.which", lambda cmd: "/usr/bin/systemctl")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        output = list(ctrl.install(("https://example.com/feed.xml",), agent="gemini"))

    run_script = tmp_path / ".local" / "share" / "news-recap" / "run.sh"
    assert run_script.exists()
    content = run_script.read_text()
    assert "--rss 'https://example.com/feed.xml'" in content
    assert "--agent gemini" in content
    assert "{{AGENT_ARGS}}" not in content
    if sys.platform != "win32":
        assert run_script.stat().st_mode & stat.S_IXUSR

    service = tmp_path / ".config" / "systemd" / "user" / "news-recap.service"
    assert service.exists()
    assert str(run_script) in service.read_text()

    timer = tmp_path / ".config" / "systemd" / "user" / "news-recap.timer"
    assert timer.exists()
    assert "03:00:00" in timer.read_text()

    assert any("Installed" in t for _, t in output)


def test_install_linux_custom_time(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")
    monkeypatch.setattr("news_recap.automation.shutil.which", lambda cmd: "/usr/bin/systemctl")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        list(ctrl.install(("https://example.com/feed.xml",), hour=22, minute=15))

    timer = tmp_path / ".config" / "systemd" / "user" / "news-recap.timer"
    assert "22:15:00" in timer.read_text()


def test_install_linux_requires_systemctl(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")
    monkeypatch.setattr("news_recap.automation.shutil.which", lambda cmd: None)

    ctrl = ScheduleController()
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

    app_dir = tmp_path / ".local" / "share" / "news-recap"
    run_script = app_dir / "run.sh"
    run_script.parent.mkdir(parents=True)
    run_script.write_text("#!/bin/bash")
    (app_dir / "schedule.json").write_text("{}")

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        output = list(ctrl.uninstall())

    assert not (systemd_dir / "news-recap.timer").exists()
    assert not (systemd_dir / "news-recap.service").exists()
    assert not run_script.exists()
    assert not (app_dir / "schedule.json").exists()
    assert any("Removed" in t for _, t in output)


def test_uninstall_linux_not_installed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "linux")

    ctrl = ScheduleController()
    output = list(ctrl.uninstall())
    assert any("Not installed" in t for _, t in output)


# ── Windows install ───────────────────────────────────────────────────


def test_install_windows_creates_script(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    with patch("news_recap.automation.subprocess.run", return_value=_MOCK_CP):
        ctrl = ScheduleController()
        output = list(ctrl.install(("https://example.com/feed.xml",), agent="claude"))

    run_script = tmp_path / "AppData" / "Local" / "news-recap" / "run.ps1"
    assert run_script.exists()
    content = run_script.read_text()
    assert "--rss 'https://example.com/feed.xml'" in content
    assert "--agent claude" in content
    assert "{{AGENT_ARGS}}" not in content
    assert "{{NEWS_RECAP_CMD}}" not in content
    assert any("scheduled task" in t.lower() for _, t in output)


# ── Windows uninstall ─────────────────────────────────────────────────


def test_uninstall_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("news_recap.automation._home", lambda: tmp_path)
    monkeypatch.setattr("news_recap.automation._platform", lambda: "windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    app_dir = tmp_path / "AppData" / "Local" / "news-recap"
    run_script = app_dir / "run.ps1"
    run_script.parent.mkdir(parents=True)
    run_script.write_text("script")
    (app_dir / "schedule.json").write_text("{}")

    mock_result = type("R", (), {"returncode": 0})()
    with patch("news_recap.automation.subprocess.run", return_value=mock_result):
        ctrl = ScheduleController()
        output = list(ctrl.uninstall())

    assert not run_script.exists()
    assert not (app_dir / "schedule.json").exists()
    assert any("Removed" in t for _, t in output)
