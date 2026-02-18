from __future__ import annotations

import stat
from pathlib import Path

from click.testing import CliRunner

from news_recap.main import news_recap


def _write_fake_agent(path: Path, name: str) -> None:
    script = f"""#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

if "--version" in sys.argv:
    print("{name} 1.0")
    raise SystemExit(0)
if "--help" in sys.argv:
    print("{name} help")
    raise SystemExit(0)

parser = argparse.ArgumentParser()
parser.add_argument("--prompt-file", default=None)
parser.add_argument("prompt", nargs="?")
args = parser.parse_args()
if args.prompt_file:
    text = Path(args.prompt_file).read_text("utf-8")
else:
    text = args.prompt or ""
print("OK" if "OK" in text else "BAD")
"""
    path.write_text(script, "utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_llm_smoke_runs_synthetic_task_without_db(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_fake_agent(bin_dir / "codex", "codex")
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path.cwd()!s}:{Path.home()!s}:{Path('/usr/bin')!s}")

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "llm",
            "smoke",
            "--agent",
            "codex",
            "--codex-command",
            "codex --prompt-file {prompt_file}",
            "--prompt",
            "Reply with exactly: OK",
            "--expect-substring",
            "OK",
        ],
    )
    assert result.exit_code == 0
    assert "agent=codex available=yes probe=ok run=ok" in result.output
    assert "Smoke status: passed" in result.output


def test_llm_smoke_fails_when_agent_executable_is_missing(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_fake_agent(bin_dir / "codex", "codex")
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path.cwd()!s}:{Path.home()!s}:{Path('/usr/bin')!s}")

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "llm",
            "smoke",
            "--agent",
            "claude",
        ],
    )
    assert result.exit_code != 0
    assert "agent=claude available=no probe=failed run=skipped" in result.output
    assert "LLM smoke check failed." in result.output


def test_llm_smoke_quotes_prompt_placeholder(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_fake_agent(bin_dir / "codex", "codex")
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path.cwd()!s}:{Path.home()!s}:{Path('/usr/bin')!s}")

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "llm",
            "smoke",
            "--agent",
            "codex",
            "--codex-command",
            "codex {prompt}",
            "--prompt",
            "Reply with exactly: OK",
            "--expect-substring",
            "OK",
        ],
    )
    assert result.exit_code == 0
    assert "agent=codex available=yes probe=ok run=ok" in result.output
