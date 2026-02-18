from __future__ import annotations

import re
import sys
from pathlib import Path

from click.testing import CliRunner

from news_recap.main import news_recap


def test_llm_cli_enqueue_worker_and_inspect(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "llm-cli.db"
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex")
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE",
        (
            f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
            "--task-manifest {task_manifest}"
        ),
    )
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKDIR_ROOT", str(tmp_path / "workdir"))

    runner = CliRunner()
    enqueue = runner.invoke(
        news_recap,
        [
            "llm",
            "enqueue-test",
            "--db-path",
            str(db_path),
            "--task-type",
            "highlights",
            "--prompt",
            "Generate highlights.",
            "--source-id",
            "article:1",
        ],
    )
    assert enqueue.exit_code == 0
    match = re.search(r"task_id=([a-f0-9-]+)", enqueue.output)
    assert match is not None
    task_id = match.group(1)

    worker = runner.invoke(
        news_recap,
        [
            "llm",
            "worker",
            "--db-path",
            str(db_path),
            "--once",
        ],
    )
    assert worker.exit_code == 0
    assert "processed=1" in worker.output
    assert "succeeded=1" in worker.output

    tasks = runner.invoke(
        news_recap,
        [
            "llm",
            "tasks",
            "--db-path",
            str(db_path),
            "--status",
            "succeeded",
        ],
    )
    assert tasks.exit_code == 0
    assert task_id in tasks.output

    inspect = runner.invoke(
        news_recap,
        [
            "llm",
            "inspect",
            "--db-path",
            str(db_path),
            "--task-id",
            task_id,
        ],
    )
    assert inspect.exit_code == 0
    assert "Status: succeeded" in inspect.output
