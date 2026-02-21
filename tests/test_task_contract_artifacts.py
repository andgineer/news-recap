from __future__ import annotations

import json
from pathlib import Path

import allure

from news_recap.brain.contracts import TaskInputContract, read_manifest
from news_recap.brain.workdir import TaskWorkdirManager

pytestmark = [
    allure.epic("Product Intelligence"),
    allure.feature("Task Contract & Context Artifacts"),
]


def test_task_manifest_v2_contains_optional_artifacts(tmp_path: Path) -> None:
    manager = TaskWorkdirManager(tmp_path / "workdir")
    materialized = manager.materialize(
        task_id="task-contract-artifacts",
        task_type="highlights",
        task_input=TaskInputContract(task_type="highlights", prompt="Prompt"),
        articles_index=[],
        continuity_summary={"items": []},
        retrieval_context={"top_k": 10},
        story_context={"stories": []},
    )

    manifest = read_manifest(materialized.manifest_path)
    assert manifest.contract_version == 2
    assert manifest.continuity_summary_path is not None
    assert manifest.retrieval_context_path is not None
    assert manifest.story_context_path is not None
    assert Path(manifest.continuity_summary_path).exists()
    assert Path(manifest.retrieval_context_path).exists()
    assert Path(manifest.story_context_path).exists()


def test_read_manifest_supports_legacy_v1_without_optional_paths(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "task_id": "task-legacy",
                "task_type": "highlights",
                "workdir": str(tmp_path),
                "task_input_path": str(tmp_path / "task_input.json"),
                "articles_index_path": str(tmp_path / "articles_index.json"),
                "output_result_path": str(tmp_path / "output.json"),
                "output_stdout_path": str(tmp_path / "stdout.log"),
                "output_stderr_path": str(tmp_path / "stderr.log"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )

    manifest = read_manifest(manifest_path)
    assert manifest.contract_version == 1
    assert manifest.continuity_summary_path is None
    assert manifest.retrieval_context_path is None
    assert manifest.story_context_path is None
