"""Workdir materialization helpers for file-based task execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from news_recap.orchestrator.contracts import (
    ArticleIndexEntry,
    TaskInputContract,
    TaskManifest,
    write_articles_index,
    write_manifest,
    write_task_input,
)


@dataclass(slots=True)
class MaterializedTask:
    """Materialized file-based task contract paths."""

    manifest_path: Path
    manifest: TaskManifest


class TaskWorkdirManager:
    """Creates deterministic per-task directory layout."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def materialize(
        self,
        *,
        task_id: str,
        task_type: str,
        task_input: TaskInputContract,
        articles_index: list[ArticleIndexEntry],
    ) -> MaterializedTask:
        base_dir = self.root_dir / task_id
        input_dir = base_dir / "input"
        output_dir = base_dir / "output"
        meta_dir = base_dir / "meta"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)

        task_input_path = input_dir / "task_input.json"
        articles_index_path = input_dir / "articles_index.json"
        output_result_path = output_dir / "agent_result.json"
        output_stdout_path = output_dir / "agent_stdout.log"
        output_stderr_path = output_dir / "agent_stderr.log"
        manifest_path = meta_dir / "task_manifest.json"

        write_task_input(task_input_path, task_input)
        write_articles_index(articles_index_path, articles_index)

        manifest = TaskManifest(
            task_id=task_id,
            task_type=task_type,
            workdir=str(base_dir),
            task_input_path=str(task_input_path),
            articles_index_path=str(articles_index_path),
            output_result_path=str(output_result_path),
            output_stdout_path=str(output_stdout_path),
            output_stderr_path=str(output_stderr_path),
        )
        write_manifest(manifest_path, manifest)

        return MaterializedTask(
            manifest_path=manifest_path,
            manifest=manifest,
        )
