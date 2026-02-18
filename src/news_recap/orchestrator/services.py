"""Use-case services for orchestrator queue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from news_recap.orchestrator.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.orchestrator.models import LlmTaskCreate, LlmTaskView
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.workdir import TaskWorkdirManager


@dataclass(slots=True)
class EnqueueDemoTask:
    """High-level command to enqueue a demo task."""

    task_type: str
    prompt: str
    source_ids: tuple[str, ...]
    priority: int = 100
    max_attempts: int = 3
    timeout_seconds: int = 600


class OrchestratorService:
    """Coordinates workdir materialization and task queue insert."""

    def __init__(
        self,
        *,
        repository: OrchestratorRepository,
        workdir_root: Path,
    ) -> None:
        self.repository = repository
        self.workdir = TaskWorkdirManager(workdir_root)

    def enqueue_demo_task(self, command: EnqueueDemoTask) -> LlmTaskView:
        """Enqueue a test/spike task with deterministic file contracts."""

        task_id = str(uuid4())
        source_ids = command.source_ids or ("source:demo",)
        materialized = self.workdir.materialize(
            task_id=task_id,
            task_type=command.task_type,
            task_input=TaskInputContract(
                task_type=command.task_type,
                prompt=command.prompt,
                metadata={},
            ),
            articles_index=[
                ArticleIndexEntry(
                    source_id=source_id,
                    title=f"Article {index + 1}",
                    url=f"https://example.com/{index + 1}",
                )
                for index, source_id in enumerate(source_ids)
            ],
        )
        return self.repository.enqueue_task(
            LlmTaskCreate(
                task_id=task_id,
                task_type=command.task_type,
                priority=command.priority,
                max_attempts=command.max_attempts,
                timeout_seconds=command.timeout_seconds,
                input_manifest_path=str(materialized.manifest_path),
                output_path=materialized.manifest.output_result_path,
            ),
        )
