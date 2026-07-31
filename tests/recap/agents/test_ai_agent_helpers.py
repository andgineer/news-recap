from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


from news_recap.recap.agents.ai_agent import (
    _inject_skip_git_flag,
    _log_agent_output,
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
"gemini-3.5-flash" --effort ""): --model gemini-3.5-flash requires --effort (available: low, medium, high)
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


def test_log_agent_output_skips_empty_files(tmp_path: Path) -> None:
    stderr_path = tmp_path / "e.log"
    stdout_path = tmp_path / "o.log"
    stderr_path.write_text("   \n", "utf-8")
    stdout_path.write_text("", "utf-8")
    result = SimpleNamespace(stderr_path=stderr_path, stdout_path=stdout_path)
    log = MagicMock()
    _log_agent_output(log, "step_x", result)
    log.error.assert_not_called()
