from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from news_recap.recap.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.recap.storage.workdir import (
    MaterializedTask,
    TaskWorkdirManager,
    make_task_id,
    materialize_step,
)


def test_task_workdir_manager_creates_dirs(tmp_path: Path) -> None:
    mgr = TaskWorkdirManager(tmp_path)
    task_input = TaskInputContract(task_type="recap_classify", prompt="p")
    entries: list[ArticleIndexEntry] = []
    mgr.materialize(
        task_id="classify",
        task_type="recap_classify",
        task_input=task_input,
        articles_index=entries,
    )
    base = tmp_path / "classify"
    assert (base / "input").is_dir()
    assert (base / "output").is_dir()
    assert (base / "meta").is_dir()


def test_task_workdir_manager_writes_manifest(tmp_path: Path) -> None:
    mgr = TaskWorkdirManager(tmp_path)
    task_input = TaskInputContract(task_type="recap_classify", prompt="p")
    entries: list[ArticleIndexEntry] = []
    materialized: MaterializedTask = mgr.materialize(
        task_id="classify",
        task_type="recap_classify",
        task_input=task_input,
        articles_index=entries,
    )
    raw = json.loads(materialized.manifest_path.read_text("utf-8"))
    assert {"contract_version", "task_id", "task_type", "workdir"} <= raw.keys()
    assert raw["task_id"] == "classify"
    assert raw["task_type"] == "recap_classify"
    assert "output_result_path" not in raw
    assert "output_stdout_path" not in raw


def test_task_workdir_manager_writes_task_input(tmp_path: Path) -> None:
    mgr = TaskWorkdirManager(tmp_path)
    prompt = "hello task"
    task_input = TaskInputContract(task_type="recap_classify", prompt=prompt)
    entries: list[ArticleIndexEntry] = []
    materialized: MaterializedTask = mgr.materialize(
        task_id="classify",
        task_type="recap_classify",
        task_input=task_input,
        articles_index=entries,
    )
    data = json.loads(materialized.manifest.task_input_path.read_text("utf-8"))
    assert data["prompt"] == prompt


def test_materialize_step_returns_task_id(tmp_path: Path) -> None:
    routing = MagicMock()
    routing.to_metadata.return_value = {"agent": "codex", "model": "x"}
    inp = SimpleNamespace(routing_defaults=object(), agent_override=None)
    mgr = TaskWorkdirManager(tmp_path)
    with patch(
        "news_recap.recap.storage.workdir.resolve_routing_for_enqueue",
        return_value=routing,
    ):
        task_id = materialize_step(
            mgr,
            inp,
            step_name="recap_classify",
            prompt="do it",
        )
    assert task_id == "classify"
    assert make_task_id("recap_classify") == "classify"


def test_materialize_step_with_batch(tmp_path: Path) -> None:
    routing = MagicMock()
    routing.to_metadata.return_value = {"agent": "codex", "model": "x"}
    inp = SimpleNamespace(routing_defaults=object(), agent_override=None)
    mgr = TaskWorkdirManager(tmp_path)
    with patch(
        "news_recap.recap.storage.workdir.resolve_routing_for_enqueue",
        return_value=routing,
    ):
        task_id = materialize_step(
            mgr,
            inp,
            step_name="recap_classify",
            batch=1,
            prompt="do it",
        )
    assert task_id == "classify-1"
    assert make_task_id("recap_classify", 1) == "classify-1"
