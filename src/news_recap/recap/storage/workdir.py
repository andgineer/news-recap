"""Workdir materialization helpers for file-based task execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from news_recap.recap.agents.routing import resolve_routing_for_enqueue
from news_recap.recap.contracts import (
    ArticleIndexEntry,
    TaskInputContract,
    TaskManifest,
    write_articles_index,
    write_manifest,
    write_task_input,
)

if TYPE_CHECKING:
    from news_recap.recap.storage.pipeline_io import PipelineInput


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
            contract_version=2,
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


def make_task_id(step_name: str, batch: int | None = None) -> str:
    """Human-readable workdir name: ``classify``, ``classify-1``, ``classify-2``."""
    short = step_name.removeprefix("recap_")
    if batch is not None:
        return f"{short}-{batch}"
    return short


def next_batch_number(pdir: Path, step_name: str) -> int:
    """Return the next available batch number for *step_name* in *pdir*.

    Scans existing workdirs like ``enrich-1``, ``enrich-2``, … and returns
    ``max + 1`` so resumed runs don't collide with earlier batches.
    """
    prefix = step_name.removeprefix("recap_") + "-"
    highest = 0
    if pdir.is_dir():
        for d in pdir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                suffix = d.name[len(prefix) :]
                if suffix.isdigit():
                    highest = max(highest, int(suffix))
    return highest + 1


def materialize_step(  # noqa: PLR0913
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    *,
    step_name: str,
    batch: int | None = None,
    article_entries: list[ArticleIndexEntry] | None = None,
    prompt: str,
) -> str:
    """Create a task workdir with all input files and return the task_id."""
    task_id = make_task_id(step_name, batch)
    entries = article_entries or []

    routing = resolve_routing_for_enqueue(
        defaults=inp.routing_defaults,
        task_type=step_name,
        agent_override=inp.agent_override,
        model_override=None,
    )

    workdir_mgr.materialize(
        task_id=task_id,
        task_type=step_name,
        task_input=TaskInputContract(
            task_type=step_name,
            prompt=prompt,
            metadata={"routing": routing.to_metadata()},
        ),
        articles_index=entries,
    )
    return task_id
