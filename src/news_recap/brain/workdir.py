"""Workdir materialization helpers for file-based task execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from news_recap.brain.contracts import (
    ArticleIndexEntry,
    TaskInputContract,
    TaskManifest,
    write_articles_index,
    write_json,
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

    def materialize(  # noqa: PLR0913
        self,
        *,
        task_id: str,
        task_type: str,
        task_input: TaskInputContract,
        articles_index: list[ArticleIndexEntry],
        continuity_summary: dict[str, object] | None = None,
        retrieval_context: dict[str, object] | None = None,
        story_context: dict[str, object] | None = None,
        extra_input_files: dict[str, str | bytes] | None = None,
        output_schema_hint: str | None = None,
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
        continuity_summary_path: Path | None = None
        retrieval_context_path: Path | None = None
        story_context_path: Path | None = None

        write_task_input(task_input_path, task_input)
        write_articles_index(articles_index_path, articles_index)
        if continuity_summary is not None:
            continuity_summary_path = input_dir / "continuity_summary.json"
            write_json(continuity_summary_path, continuity_summary)
        if retrieval_context is not None:
            retrieval_context_path = input_dir / "retrieval_context.json"
            write_json(retrieval_context_path, retrieval_context)
        if story_context is not None:
            story_context_path = input_dir / "story_context.json"
            write_json(story_context_path, story_context)

        input_resources_dir: Path | None = None
        output_results_dir: Path | None = None

        if extra_input_files:
            input_resources_dir = input_dir / "resources"
            input_resources_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in extra_input_files.items():
                file_path = input_resources_dir / filename
                if isinstance(content, bytes):
                    file_path.write_bytes(content)
                else:
                    file_path.write_text(content, "utf-8")
            output_results_dir = output_dir / "results"
            output_results_dir.mkdir(parents=True, exist_ok=True)

        contract_version = 3 if (input_resources_dir or output_schema_hint) else 2

        manifest = TaskManifest(
            contract_version=contract_version,
            task_id=task_id,
            task_type=task_type,
            workdir=str(base_dir),
            task_input_path=str(task_input_path),
            articles_index_path=str(articles_index_path),
            output_result_path=str(output_result_path),
            output_stdout_path=str(output_stdout_path),
            output_stderr_path=str(output_stderr_path),
            continuity_summary_path=(
                str(continuity_summary_path) if continuity_summary_path is not None else None
            ),
            retrieval_context_path=(
                str(retrieval_context_path) if retrieval_context_path is not None else None
            ),
            story_context_path=str(story_context_path) if story_context_path is not None else None,
            input_resources_dir=(
                str(input_resources_dir) if input_resources_dir is not None else None
            ),
            output_results_dir=(
                str(output_results_dir) if output_results_dir is not None else None
            ),
            output_schema_hint=output_schema_hint,
        )
        write_manifest(manifest_path, manifest)

        return MaterializedTask(
            manifest_path=manifest_path,
            manifest=manifest,
        )
