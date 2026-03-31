"""Manage daily scheduled automation for news-recap."""

# ruff: noqa: S603, S607

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

import click

Severity = Literal["ok", "info", "warn", "error", "log", "heading"]
AutoLine = tuple[Severity, str]


def resolve_rss_urls(cli_urls: tuple[str, ...]) -> tuple[str, ...]:
    """Return RSS URLs from *cli_urls* or ``NEWS_RECAP_RSS_FEED_URLS``; error if neither."""
    if cli_urls:
        return cli_urls
    raw = os.getenv("NEWS_RECAP_RSS_FEED_URLS", "").strip()
    if raw:
        urls = tuple(u.strip() for u in raw.split(",") if u.strip())
        if urls:
            return urls
    raise click.UsageError(
        "No RSS feed URLs provided. Pass --rss URL or set NEWS_RECAP_RSS_FEED_URLS.",
    )


_LAUNCHD_LABEL = "com.news-recap.daily"
_SYSTEMD_SERVICE = "news-recap"
_WINDOWS_TASK = "news-recap-daily"


def _platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "windows"
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _build_rss_args(rss_urls: tuple[str, ...]) -> str:
    parts: list[str] = []
    for url in rss_urls:
        parts.append(f"--rss '{url}'")
    return " ".join(parts)


def _build_agent_args(agent: str | None) -> str:
    return f"--agent {agent}" if agent else ""


def _read_template(name: str) -> str:
    return files("news_recap.scripts").joinpath(name).read_text(encoding="utf-8")


def _home() -> Path:
    return Path.home()


def _today_log_name() -> str:
    return f"news-recap-{datetime.now(tz=UTC).strftime('%Y-%m-%d')}.log"


def _start_failed(
    cmd: str,
    result: subprocess.CompletedProcess[bytes],
) -> Iterator[AutoLine]:
    stderr = result.stderr.decode(errors="replace").strip() if result.stderr else ""
    msg = f"{cmd} failed (exit {result.returncode})"
    if stderr:
        msg += f": {stderr}"
    yield ("error", msg)


_RESULT_MARKER = "===== RESULT:"


def _wait_for_new_output(
    log_file: Path,
    offset: int,
    timeout: float = 30.0,
) -> list[str]:
    """Wait until the result marker appears in bytes written after *offset*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_file.exists() and log_file.stat().st_size > offset:
            tail = log_file.read_text(encoding="utf-8", errors="replace")[offset:]
            if _RESULT_MARKER in tail:
                return tail.strip().splitlines()
        time.sleep(0.5)
    if log_file.exists() and log_file.stat().st_size > offset:
        return log_file.read_text(encoding="utf-8", errors="replace")[offset:].strip().splitlines()
    return []


def _emit_log_lines(lines: list[str]) -> Iterator[AutoLine]:
    """Yield tagged log lines; detect success/failure from RESULT marker."""
    success = any("RESULT: OK" in ln for ln in lines)
    failed = any("RESULT: FAILED" in ln for ln in lines)
    for line in lines:
        if _RESULT_MARKER in line:
            if "RESULT: OK" in line:
                yield ("ok", line)
            else:
                yield ("error", line)
        elif failed:
            yield ("error", line)
        else:
            yield ("log", line)
    if failed:
        yield ("error", "Test run failed — check the log above")
    elif success:
        yield ("ok", "Test run succeeded")


class AutoController:
    """Install / uninstall platform-native daily scheduler for news-recap."""

    def install(
        self,
        rss_urls: tuple[str, ...],
        agent: str | None = None,
    ) -> Iterator[AutoLine]:
        platform = _platform()
        rss_args = _build_rss_args(rss_urls)
        agent_args = _build_agent_args(agent)

        if platform == "macos":
            yield from self._install_macos(rss_args, agent_args)
        elif platform == "linux":
            yield from self._install_linux(rss_args, agent_args)
        elif platform == "windows":
            yield from self._install_windows(rss_args, agent_args)

    def uninstall(self) -> Iterator[AutoLine]:
        platform = _platform()

        if platform == "macos":
            yield from self._uninstall_macos()
        elif platform == "linux":
            yield from self._uninstall_linux()
        elif platform == "windows":
            yield from self._uninstall_windows()

    # ── macOS ──────────────────────────────────────────────────────────

    def _install_macos(self, rss_args: str, agent_args: str) -> Iterator[AutoLine]:
        home = _home()
        run_script = home / "Library" / "Application Support" / "news-recap" / "run.sh"
        plist_path = home / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        log_dir = home / "Library" / "Logs" / "news-recap"
        log_file = log_dir / _today_log_name()
        stdout_log = log_dir / "launchd.out.log"
        stderr_log = log_dir / "launchd.err.log"

        run_script.parent.mkdir(parents=True, exist_ok=True)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        content = _read_template("macos_run.sh")
        content = content.replace("{{RSS_ARGS}}", rss_args)
        content = content.replace("{{AGENT_ARGS}}", agent_args)
        run_script.write_text(content, encoding="utf-8")
        run_script.chmod(run_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        yield ("ok", f"Runner script: {run_script}")

        plist_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>{run_script}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>3</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
  </dict>
</plist>"""
        plist_path.write_text(plist_content, encoding="utf-8")

        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            check=True,
        )
        yield ("ok", f"Installed LaunchAgent: {plist_path}")
        yield ("info", f"Logs: {log_dir}")

        yield ("heading", "Starting test run…")
        offset = log_file.stat().st_size if log_file.exists() else 0
        result = subprocess.run(
            ["launchctl", "start", _LAUNCHD_LABEL],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            yield from _start_failed("launchctl start", result)
        else:
            new_lines = _wait_for_new_output(log_file, offset)
            if new_lines:
                yield from _emit_log_lines(new_lines[:40])
            else:
                yield ("warn", f"No output after 30 s — check: tail -f {log_file}")

    def _uninstall_macos(self) -> Iterator[AutoLine]:
        home = _home()
        plist_path = home / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        run_script = home / "Library" / "Application Support" / "news-recap" / "run.sh"

        if plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
                check=False,
            )
            plist_path.unlink()
            yield ("ok", f"Removed: {plist_path}")
        else:
            yield ("info", "Not installed (no LaunchAgent found)")

        if run_script.exists():
            run_script.unlink()
            yield ("ok", f"Removed: {run_script}")

    # ── Linux ──────────────────────────────────────────────────────────

    def _install_linux(self, rss_args: str, agent_args: str) -> Iterator[AutoLine]:
        home = _home()
        run_script = home / ".local" / "share" / "news-recap" / "run.sh"
        systemd_dir = home / ".config" / "systemd" / "user"
        service_path = systemd_dir / f"{_SYSTEMD_SERVICE}.service"
        timer_path = systemd_dir / f"{_SYSTEMD_SERVICE}.timer"

        run_script.parent.mkdir(parents=True, exist_ok=True)
        systemd_dir.mkdir(parents=True, exist_ok=True)

        if shutil.which("systemctl") is None:
            raise RuntimeError("systemctl not found — systemd is required on Linux")

        content = _read_template("linux_run.sh")
        content = content.replace("{{RSS_ARGS}}", rss_args)
        content = content.replace("{{AGENT_ARGS}}", agent_args)
        run_script.write_text(content, encoding="utf-8")
        run_script.chmod(run_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        yield ("ok", f"Runner script: {run_script}")

        service_path.write_text(
            f"""\
[Unit]
Description=Run news-recap pipeline

[Service]
Type=oneshot
ExecStart={run_script}
""",
            encoding="utf-8",
        )

        timer_path.write_text(
            """\
[Unit]
Description=Run news-recap daily

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
""",
            encoding="utf-8",
        )

        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{_SYSTEMD_SERVICE}.timer"],
            check=True,
        )
        yield ("ok", f"Installed: {service_path}")
        yield ("ok", f"Installed: {timer_path}")

        log_dir = home / ".local" / "state" / "news-recap"
        log_file = log_dir / _today_log_name()
        yield ("heading", "Starting test run…")
        offset = log_file.stat().st_size if log_file.exists() else 0
        result = subprocess.run(
            ["systemctl", "--user", "start", f"{_SYSTEMD_SERVICE}.service"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            yield from _start_failed("systemctl start", result)
        else:
            new_lines = _wait_for_new_output(log_file, offset)
            if new_lines:
                yield from _emit_log_lines(new_lines[:40])
            else:
                yield (
                    "warn",
                    "No output after 30 s — check: "
                    f"journalctl --user -u {_SYSTEMD_SERVICE}.service -n 30",
                )

    def _uninstall_linux(self) -> Iterator[AutoLine]:
        home = _home()
        systemd_dir = home / ".config" / "systemd" / "user"
        service_path = systemd_dir / f"{_SYSTEMD_SERVICE}.service"
        timer_path = systemd_dir / f"{_SYSTEMD_SERVICE}.timer"
        run_script = home / ".local" / "share" / "news-recap" / "run.sh"

        had_units = timer_path.exists() or service_path.exists()

        if timer_path.exists():
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", f"{_SYSTEMD_SERVICE}.timer"],
                capture_output=True,
                check=False,
            )
            timer_path.unlink()
            yield ("ok", f"Removed: {timer_path}")

        if service_path.exists():
            service_path.unlink()
            yield ("ok", f"Removed: {service_path}")

        if had_units:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                check=False,
            )
        else:
            yield ("info", "Not installed (no systemd units found)")

        if run_script.exists():
            run_script.unlink()
            yield ("ok", f"Removed: {run_script}")

    # ── Windows ────────────────────────────────────────────────────────

    def _install_windows(self, rss_args: str, agent_args: str) -> Iterator[AutoLine]:
        local_app = Path(os.environ.get("LOCALAPPDATA", str(_home() / "AppData" / "Local")))
        run_script = local_app / "news-recap" / "run.ps1"
        log_dir = local_app / "news-recap" / "logs"

        run_script.parent.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        content = _read_template("windows_run.ps1")
        content = content.replace("{{RSS_ARGS}}", rss_args)
        content = content.replace("{{AGENT_ARGS}}", agent_args)
        run_script.write_text(content, encoding="utf-8")
        yield ("ok", f"Runner script: {run_script}")

        subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    f'$action = New-ScheduledTaskAction -Execute "powershell.exe" '
                    f"-Argument \"-ExecutionPolicy Bypass -File '{run_script}'\"; "
                    f"$trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM; "
                    f'Register-ScheduledTask -TaskName "{_WINDOWS_TASK}" '
                    f'-Action $action -Trigger $trigger -Description "news-recap daily" '
                    f"-Force | Out-Null"
                ),
            ],
            check=True,
        )
        yield ("ok", f"Installed scheduled task: {_WINDOWS_TASK}")

        log_file = log_dir / _today_log_name()
        yield ("heading", "Starting test run…")
        offset = log_file.stat().st_size if log_file.exists() else 0
        result = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f'Start-ScheduledTask -TaskName "{_WINDOWS_TASK}"',
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            yield from _start_failed("Start-ScheduledTask", result)
        else:
            new_lines = _wait_for_new_output(log_file, offset)
            if new_lines:
                yield from _emit_log_lines(new_lines[:40])
            else:
                yield ("warn", f"No output after 30 s — check: Get-Content '{log_file}' -Tail 30")

    def _uninstall_windows(self) -> Iterator[AutoLine]:
        local_app = Path(os.environ.get("LOCALAPPDATA", str(_home() / "AppData" / "Local")))
        run_script = local_app / "news-recap" / "run.ps1"

        result = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f'Unregister-ScheduledTask -TaskName "{_WINDOWS_TASK}" -Confirm:$false',
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            yield ("ok", f"Removed scheduled task: {_WINDOWS_TASK}")
        else:
            yield ("info", f"Scheduled task not found: {_WINDOWS_TASK}")

        if run_script.exists():
            run_script.unlink()
            yield ("ok", f"Removed: {run_script}")
