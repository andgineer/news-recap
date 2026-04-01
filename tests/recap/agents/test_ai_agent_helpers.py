from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


from news_recap.recap.agents.ai_agent import _inject_skip_git_flag, _log_agent_output


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


def test_log_agent_output_skips_empty_files(tmp_path: Path) -> None:
    stderr_path = tmp_path / "e.log"
    stdout_path = tmp_path / "o.log"
    stderr_path.write_text("   \n", "utf-8")
    stdout_path.write_text("", "utf-8")
    result = SimpleNamespace(stderr_path=stderr_path, stdout_path=stdout_path)
    log = MagicMock()
    _log_agent_output(log, "step_x", result)
    log.error.assert_not_called()
