"""Use-case services for orchestrator queue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from news_recap.orchestrator.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.orchestrator.models import LlmTaskCreate, LlmTaskView, SourceCorpusEntry
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import (
    RoutingDefaults,
    resolve_routing_for_enqueue,
)
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
    agent: str | None = None
    model_profile: str | None = None
    model: str | None = None
    metadata: dict[str, object] | None = None


class OrchestratorService:
    """Coordinates workdir materialization and task queue insert."""

    def __init__(
        self,
        *,
        repository: OrchestratorRepository,
        workdir_root: Path,
        routing_defaults: RoutingDefaults,
    ) -> None:
        self.repository = repository
        self.workdir = TaskWorkdirManager(workdir_root)
        self.routing_defaults = routing_defaults

    def enqueue_demo_task(self, command: EnqueueDemoTask) -> LlmTaskView:
        """Enqueue a test/spike task with deterministic file contracts."""

        task_id = str(uuid4())
        article_entries = self._resolve_article_entries(source_ids=command.source_ids)
        routing = resolve_routing_for_enqueue(
            defaults=self.routing_defaults,
            task_type=command.task_type,
            agent_override=command.agent,
            profile_override=command.model_profile,
            model_override=command.model,
        )
        materialized = self.workdir.materialize(
            task_id=task_id,
            task_type=command.task_type,
            task_input=TaskInputContract(
                task_type=command.task_type,
                prompt=command.prompt,
                metadata={
                    "routing": routing.to_metadata(),
                    **(command.metadata or {}),
                },
            ),
            articles_index=[
                ArticleIndexEntry(
                    source_id=entry.source_id,
                    title=entry.title,
                    url=entry.url,
                    source=entry.source,
                    published_at=entry.published_at.isoformat(),
                )
                for entry in article_entries
            ],
        )
        task = self.repository.enqueue_task(
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
        self.repository.add_task_event(
            task_id=task.task_id,
            event_type="routing_resolved",
            details={
                "routing": routing.to_metadata(),
            },
        )
        return task

    def _resolve_article_entries(self, *, source_ids: tuple[str, ...]) -> list[SourceCorpusEntry]:
        if source_ids:
            entries, missing = self.repository.validate_user_source_ids(source_ids=source_ids)
            if missing:
                raise ValueError(
                    "Unknown source_ids for current user scope: "
                    f"{', '.join(missing)}. "
                    "Use source IDs from your user corpus (format: article:<article_id>).",
                )
            return entries

        entries = self.repository.list_user_retrieval_articles(limit=20)
        if not entries:
            raise ValueError(
                "No user-scoped articles available for task source mapping. "
                "Run ingestion first or pass --source-id article:<article_id>.",
            )
        return entries
