"""Manage daily scheduled automation for news-recap."""

# ruff: noqa: S603, S607

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

import click

Severity = Literal["ok", "info", "warn", "error", "log", "heading"]
ScheduleLine = tuple[Severity, str]


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
_SCHEDULE_FILE = "schedule.json"


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


def _app_dir(platform: str) -> Path:
    """Platform-specific application data directory for news-recap."""
    home = _home()
    if platform == "macos":
        return home / "Library" / "Application Support" / "news-recap"
    if platform == "linux":
        return home / ".local" / "share" / "news-recap"
    local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    return local_app / "news-recap"


def _log_dir(platform: str) -> Path:
    """Platform-specific log directory for news-recap."""
    home = _home()
    if platform == "macos":
        return home / "Library" / "Logs" / "news-recap"
    if platform == "linux":
        return home / ".local" / "state" / "news-recap"
    local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    return local_app / "news-recap" / "logs"


def _emit_log_lines(lines: list[str]) -> Iterator[ScheduleLine]:
    """Yield log lines as context output."""
    for line in lines:
        yield ("log", line)


def _save_schedule_meta(  # noqa: PLR0913
    app_dir: Path,
    *,
    hour: int,
    minute: int,
    rss_urls: tuple[str, ...],
    agent: str | None,
    venv_bin: str | None,
) -> None:
    meta = {
        "time": f"{hour:02d}:{minute:02d}",
        "venv": venv_bin is not None,
        "venv_bin": venv_bin,
        "rss_urls": list(rss_urls),
        "agent": agent,
    }
    (app_dir / _SCHEDULE_FILE).write_text(
        json.dumps(meta, indent=2) + "\n",
        encoding="utf-8",
    )


def _remove_schedule_meta(app_dir: Path) -> None:
    meta_file = app_dir / _SCHEDULE_FILE
    if meta_file.exists():
        meta_file.unlink()


_SMOKE_LIMIT = 5


def _verify_setup(
    cmd: str,
    rss_urls: tuple[str, ...],
    agent: str | None,
    log_file: Path,
) -> Iterator[ScheduleLine]:
    """Run ingest + classify-only to verify the environment without producing a digest."""
    yield ("heading", "Verifying setup…")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    offset = log_file.stat().st_size if log_file.exists() else 0

    ingest_args = [cmd, "ingest"]
    for url in rss_urls:
        ingest_args.extend(["--rss", url])
    result = subprocess.run(
        ingest_args,
        capture_output=True,
        text=True,
        check=False,
    )
    _append_to_log(log_file, f"smoke-test: ingest exit={result.returncode}")
    if result.returncode != 0:
        _append_to_log(log_file, result.stderr or result.stdout or "")
        yield ("error", f"Verification failed: ingest (exit {result.returncode})")
        yield from _emit_log_lines(_read_log_tail(log_file, offset))
        return

    create_args = [cmd, "create", "--stop-after", "classify", "--limit", str(_SMOKE_LIMIT)]
    if agent:
        create_args.extend(["--agent", agent])
    result = subprocess.run(
        create_args,
        capture_output=True,
        text=True,
        check=False,
    )
    _append_to_log(log_file, f"smoke-test: create --stop-after classify exit={result.returncode}")
    if result.returncode != 0:
        _append_to_log(log_file, result.stderr or result.stdout or "")
        yield ("error", f"Verification failed: agent not responding (exit {result.returncode})")
        yield from _emit_log_lines(_read_log_tail(log_file, offset))
    else:
        yield ("ok", "Verification passed (feeds and agent are working)")


def _append_to_log(log_file: Path, text: str) -> None:
    with log_file.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def _read_log_tail(log_file: Path, offset: int, max_lines: int = 30) -> list[str]:
    if not log_file.exists():
        return []
    content = log_file.read_text(encoding="utf-8", errors="replace")[offset:]
    return content.strip().splitlines()[-max_lines:]


class ScheduleController:
    """Install / uninstall / query platform-native daily scheduler for news-recap."""

    def install(
        self,
        rss_urls: tuple[str, ...],
        agent: str | None = None,
        *,
        hour: int = 3,
        minute: int = 0,
        venv_bin: str | None = None,
    ) -> Iterator[ScheduleLine]:
        platform = _platform()
        rss_args = _build_rss_args(rss_urls)
        agent_args = _build_agent_args(agent)
        cmd = venv_bin or "news-recap"

        app_dir = _app_dir(platform)
        app_dir.mkdir(parents=True, exist_ok=True)
        _save_schedule_meta(
            app_dir,
            hour=hour,
            minute=minute,
            rss_urls=rss_urls,
            agent=agent,
            venv_bin=venv_bin,
        )

        if platform == "macos":
            yield from self._install_macos(
                rss_args,
                agent_args,
                hour=hour,
                minute=minute,
                venv_bin=venv_bin,
            )
        elif platform == "linux":
            yield from self._install_linux(
                rss_args,
                agent_args,
                hour=hour,
                minute=minute,
                venv_bin=venv_bin,
            )
        elif platform == "windows":
            yield from self._install_windows(
                rss_args,
                agent_args,
                hour=hour,
                minute=minute,
                venv_bin=venv_bin,
            )

        log_file = _log_dir(platform) / _today_log_name()
        yield from _verify_setup(cmd, rss_urls, agent, log_file)

    def uninstall(self) -> Iterator[ScheduleLine]:
        platform = _platform()

        if platform == "macos":
            yield from self._uninstall_macos()
        elif platform == "linux":
            yield from self._uninstall_linux()
        elif platform == "windows":
            yield from self._uninstall_windows()

        _remove_schedule_meta(_app_dir(platform))

    def get_schedule(self) -> Iterator[ScheduleLine]:
        platform = _platform()
        meta_file = _app_dir(platform) / _SCHEDULE_FILE
        if not meta_file.exists():
            yield ("info", "No schedule configured.")
            return
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        yield ("heading", "Current schedule:")
        yield ("info", f"  Time: {meta.get('time', '?')}")
        yield ("info", f"  Venv: {meta.get('venv_bin') or 'no (global news-recap)'}")
        agent = meta.get("agent")
        yield ("info", f"  Agent: {agent or 'default'}")
        rss = meta.get("rss_urls", [])
        if rss:
            yield ("info", f"  RSS feeds: {len(rss)}")
            for url in rss:
                yield ("info", f"    {url}")

    # ── macOS ──────────────────────────────────────────────────────────

    def _install_macos(
        self,
        rss_args: str,
        agent_args: str,
        *,
        hour: int,
        minute: int,
        venv_bin: str | None,
    ) -> Iterator[ScheduleLine]:
        home = _home()
        run_script = home / "Library" / "Application Support" / "news-recap" / "run.sh"
        plist_path = home / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        log_dir = home / "Library" / "Logs" / "news-recap"
        stdout_log = log_dir / "launchd.out.log"
        stderr_log = log_dir / "launchd.err.log"

        run_script.parent.mkdir(parents=True, exist_ok=True)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        content = _read_template("macos_run.sh")
        content = content.replace("{{RSS_ARGS}}", rss_args)
        content = content.replace("{{AGENT_ARGS}}", agent_args)
        content = content.replace("{{NEWS_RECAP_CMD}}", venv_bin or "news-recap")
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
      <integer>{hour}</integer>
      <key>Minute</key>
      <integer>{minute}</integer>
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

    def _uninstall_macos(self) -> Iterator[ScheduleLine]:
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

    def _install_linux(
        self,
        rss_args: str,
        agent_args: str,
        *,
        hour: int,
        minute: int,
        venv_bin: str | None,
    ) -> Iterator[ScheduleLine]:
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
        content = content.replace("{{NEWS_RECAP_CMD}}", venv_bin or "news-recap")
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
            f"""\
[Unit]
Description=Run news-recap daily

[Timer]
OnCalendar=*-*-* {hour:02d}:{minute:02d}:00
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

    def _uninstall_linux(self) -> Iterator[ScheduleLine]:
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

    def _install_windows(
        self,
        rss_args: str,
        agent_args: str,
        *,
        hour: int,
        minute: int,
        venv_bin: str | None,
    ) -> Iterator[ScheduleLine]:
        local_app = Path(os.environ.get("LOCALAPPDATA", str(_home() / "AppData" / "Local")))
        run_script = local_app / "news-recap" / "run.ps1"
        log_dir = local_app / "news-recap" / "logs"

        run_script.parent.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        content = _read_template("windows_run.ps1")
        content = content.replace("{{RSS_ARGS}}", rss_args)
        content = content.replace("{{AGENT_ARGS}}", agent_args)
        content = content.replace("{{NEWS_RECAP_CMD}}", venv_bin or "news-recap")
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
                    f"$trigger = New-ScheduledTaskTrigger -Daily -At {hour:02d}:{minute:02d}; "
                    f'Register-ScheduledTask -TaskName "{_WINDOWS_TASK}" '
                    f"-Action $action -Trigger $trigger "
                    f'-Description "news-recap daily" '
                    f"-Force | Out-Null"
                ),
            ],
            check=True,
        )
        yield ("ok", f"Installed scheduled task: {_WINDOWS_TASK}")

    def _uninstall_windows(self) -> Iterator[ScheduleLine]:
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
