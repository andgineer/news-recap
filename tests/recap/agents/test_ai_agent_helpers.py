from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


from news_recap.recap.agents.ai_agent import (
    _format_duration,
    _inject_skip_git_flag,
    _log_agent_output,
    _parse_reset_in,
    _summarise_stderr,
)

# Trimmed from a real agy run: the not-logged-in lines are startup noise, the
# invalid model selection at the end is the actual failure.
_AGY_EFFORT_FAILURE = """\
E0731 16:08:48.102875 errorreport.go:223] error getting token source: You are not logged into Antigravity.
I0731 16:08:48.150031 keyring.go:81] keyringAuth: loaded token, expired=false
I0731 16:08:49.527954 auth.go:137] ChainedAuth: authenticated via keyring (effective: keyring)
I0731 16:08:50.858103 printmode.go:346] Print mode: silent auth succeeded
E0731 16:08:52.211741 printmode.go:221] Print mode: invalid model selection (--model \
"gemini-3.7-flash" --effort ""): --model gemini-3.7-flash requires --effort (available: low, medium, high)
"""


def test_inject_skip_git_list_with_exec() -> None:
    inp = ["codex", "exec", "--model", "o3"]
    out = _inject_skip_git_flag(inp)
    assert out == ["codex", "exec", "--skip-git-repo-check", "--model", "o3"]
    assert inp == ["codex", "exec", "--model", "o3"]


def test_inject_skip_git_list_no_exec() -> None:
    inp = ["codex", "--model", "o3"]
    out = _inject_skip_git_flag(inp)
    assert out == ["codex", "--skip-git-repo-check", "--model", "o3"]


def test_inject_skip_git_list_already_present() -> None:
    inp = ["codex", "exec", "--skip-git-repo-check", "--model", "o3"]
    out = _inject_skip_git_flag(inp)
    assert out == inp


def test_inject_skip_git_string() -> None:
    s = "codex exec --model o3"
    out = _inject_skip_git_flag(s)
    assert out == "codex exec --skip-git-repo-check --model o3"


def test_inject_skip_git_string_already_present() -> None:
    s = "codex exec --skip-git-repo-check --model o3"
    out = _inject_skip_git_flag(s)
    assert out == s


def test_log_agent_output_reads_stderr_and_stdout(tmp_path: Path) -> None:
    stderr_path = tmp_path / "e.log"
    stdout_path = tmp_path / "o.log"
    stderr_path.write_text("plain stderr line\n", "utf-8")
    stdout_path.write_text("plain stdout line\n", "utf-8")
    result = SimpleNamespace(stderr_path=stderr_path, stdout_path=stdout_path)
    log = MagicMock()
    _log_agent_output(log, "step_x", result)
    assert log.error.call_count == 2


def test_log_agent_output_skips_missing_files(tmp_path: Path) -> None:
    result = SimpleNamespace(stderr_path=tmp_path / "missing_e", stdout_path=tmp_path / "missing_o")
    log = MagicMock()
    _log_agent_output(log, "step_x", result)
    log.error.assert_not_called()


def test_summarise_ignores_startup_not_logged_in_noise() -> None:
    assert _summarise_stderr(_AGY_EFFORT_FAILURE) == (
        "Invalid model/effort selection — check the agent's --model flags"
    )


def test_summarise_reports_login_when_auth_never_succeeded() -> None:
    text = "error getting token source: You are not logged into Antigravity.\n"
    assert _summarise_stderr(text) == "Not logged into Antigravity — run: agy login"


def test_summarise_ignores_429_inside_pids_and_trace_ids() -> None:
    text = "I0731 16:08:52.167611  4291 quota_manager.go:44] Trace: 0x429fe3d6590b3df6\n"
    assert _summarise_stderr(text) is None


def test_summarise_detects_real_429_status() -> None:
    text = "request failed with status 429\n"
    assert _summarise_stderr(text) == "API rate limit hit — reduce parallelism or wait"


def test_log_agent_output_does_not_blame_login_for_startup_noise(tmp_path: Path) -> None:
    stderr_path = tmp_path / "e.log"
    stdout_path = tmp_path / "o.log"
    stderr_path.write_text(_AGY_EFFORT_FAILURE, "utf-8")
    stdout_path.write_text("", "utf-8")
    result = SimpleNamespace(stderr_path=stderr_path, stdout_path=stdout_path)
    log = MagicMock()
    _log_agent_output(log, "recap_classify", result)
    logged = " ".join(str(call) for call in log.error.call_args_list)
    assert "agy login" not in logged
    assert "Invalid model/effort selection" in logged


def test_parse_reset_in_agy_format() -> None:
    assert _parse_reset_in("Resets in 103h45m22s.") == timedelta(hours=103, minutes=45, seconds=22)
    assert _parse_reset_in("Resets in 2d3h.") == timedelta(days=2, hours=3)
    assert _parse_reset_in("no reset here") is None


def test_format_duration() -> None:
    assert _format_duration(timedelta(hours=103, minutes=45)) == "4d 7h 45m"
    assert _format_duration(timedelta(minutes=45)) == "45m"
    assert _format_duration(timedelta(seconds=20)) == "less than a minute"


def test_summarise_quota_reports_weekly_window_and_reset_time() -> None:
    text = (
        "Error: Individual quota reached. Please upgrade your subscription "
        "to increase your limits. Resets in 103h45m22s.\n"
    )
    reset_at = datetime.now().astimezone() + timedelta(hours=103, minutes=45, seconds=22)
    summary = _summarise_stderr(text)
    assert summary is not None
    assert "weekly quota exhausted" in summary
    assert "4d 7h 45m" in summary
    assert reset_at.strftime("%Y-%m-%d %H:%M") in summary
    assert "retrying today will not help" in summary


def test_summarise_quota_treats_short_window_as_daily() -> None:
    summary = _summarise_stderr("Individual quota reached. Resets in 3h20m.")
    assert summary is not None
    assert "daily quota exhausted" in summary
    assert "3h 20m" in summary


def test_summarise_quota_without_reset_time() -> None:
    summary = _summarise_stderr("Please upgrade your subscription to increase your limits.")
    assert summary is not None
    assert "no reset time reported" in summary


def test_log_agent_output_points_at_full_log(tmp_path: Path) -> None:
    stderr_path = tmp_path / "e.log"
    stdout_path = tmp_path / "o.log"
    stderr_path.write_text("Individual quota reached. Resets in 3h20m.\n", "utf-8")
    stdout_path.write_text("", "utf-8")
    result = SimpleNamespace(stderr_path=stderr_path, stdout_path=stdout_path)
    log = MagicMock()
    _log_agent_output(log, "recap_classify", result)
    fmt, *args = log.error.call_args_list[0].args
    assert "Full agent log: %s" in fmt
    assert stderr_path in args


def test_log_agent_output_skips_empty_files(tmp_path: Path) -> None:
    stderr_path = tmp_path / "e.log"
    stdout_path = tmp_path / "o.log"
    stderr_path.write_text("   \n", "utf-8")
    stdout_path.write_text("", "utf-8")
    result = SimpleNamespace(stderr_path=stderr_path, stdout_path=stdout_path)
    log = MagicMock()
    _log_agent_output(log, "step_x", result)
    log.error.assert_not_called()
