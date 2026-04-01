from __future__ import annotations

import logging
import os
import sys
import threading

import pytest

from news_recap.recap.agents.subprocess import (
    SubprocessResult,
    _check_output,
    run_subprocess,
)


def test_run_subprocess_captures_output(tmp_path) -> None:
    stdout_path = tmp_path / "out.txt"
    stderr_path = tmp_path / "err.txt"
    run_args = [sys.executable, "-c", "print('hello')"]
    result = run_subprocess(
        run_args=run_args,
        env=os.environ.copy(),
        cwd=None,
        timeout_seconds=30,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    assert result == SubprocessResult(
        exit_code=0,
        timed_out=False,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    assert "hello" in stdout_path.read_text(encoding="utf-8")


def test_run_subprocess_timeout(tmp_path) -> None:
    stdout_path = tmp_path / "out.txt"
    stderr_path = tmp_path / "err.txt"
    run_args = [sys.executable, "-c", "import time; time.sleep(60)"]
    result = run_subprocess(
        run_args=run_args,
        env=os.environ.copy(),
        cwd=None,
        timeout_seconds=1,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    assert result.timed_out is True
    assert result.exit_code == 124


def test_run_subprocess_stop_event(tmp_path) -> None:
    stdout_path = tmp_path / "out.txt"
    stderr_path = tmp_path / "err.txt"
    stop_event = threading.Event()
    stop_event.set()
    run_args = [sys.executable, "-c", "import time; time.sleep(60)"]
    result = run_subprocess(
        run_args=run_args,
        env=os.environ.copy(),
        cwd=None,
        timeout_seconds=300,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stop_event=stop_event,
    )
    assert result.exit_code == 130
    assert result.timed_out is False


def test_check_output_no_file(tmp_path) -> None:
    missing = tmp_path / "nope.txt"
    offset = 7
    assert _check_output(missing, offset, "", "stdout") == offset


def test_check_output_reads_new_bytes(tmp_path) -> None:
    path = tmp_path / "log.txt"
    path.write_text("hello\n", encoding="utf-8")
    new_size = _check_output(path, 0, "", "stdout")
    assert new_size == path.stat().st_size


def test_check_output_logs_notable_lines(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "log.txt"
    path.write_text("quota exceeded\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="news_recap.recap.agents.subprocess"):
        _check_output(path, 0, "lbl", "stdout")
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert "quota" in caplog.text.lower()
