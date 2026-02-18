"""Controllers for orchestrator CLI commands."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from news_recap.config import Settings
from news_recap.orchestrator.backend import CliAgentBackend
from news_recap.orchestrator.models import LlmTaskStatus
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import SUPPORTED_AGENTS, RoutingDefaults
from news_recap.orchestrator.services import EnqueueDemoTask, OrchestratorService
from news_recap.orchestrator.smoke import AgentSmokeSpec, run_smoke_checks
from news_recap.orchestrator.worker import OrchestratorWorker


@dataclass(slots=True)
class LlmEnqueueCommand:
    """CLI input for demo task enqueue."""

    db_path: Path | None
    task_type: str
    prompt: str
    source_ids: tuple[str, ...]
    priority: int
    max_attempts: int
    timeout_seconds: int
    agent: str | None
    model_profile: str | None
    model: str | None


@dataclass(slots=True)
class LlmWorkerCommand:
    """CLI input for worker execution."""

    db_path: Path | None
    once: bool
    max_tasks: int | None


@dataclass(slots=True)
class LlmListTasksCommand:
    """CLI input for task listing."""

    db_path: Path | None
    status: str | None
    limit: int


@dataclass(slots=True)
class LlmInspectTaskCommand:
    """CLI input for task inspection."""

    db_path: Path | None
    task_id: str


@dataclass(slots=True)
class LlmMutateTaskCommand:
    """CLI input for retry/cancel operations."""

    db_path: Path | None
    task_id: str


@dataclass(slots=True)
class LlmSmokeCommand:
    """CLI input for direct agent smoke check."""

    agents: tuple[str, ...]
    model_profile: str
    model: str | None
    prompt: str
    expect_substring: str
    timeout_seconds: int
    claude_command: str | None
    codex_command: str | None
    gemini_command: str | None


@dataclass(slots=True)
class LlmSmokeResult:
    """Smoke-check report to render in CLI."""

    lines: list[str]
    success: bool


class OrchestratorCliController:
    """Coordinates queue, worker, and inspection CLI operations."""

    def enqueue_demo(self, command: LlmEnqueueCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = _routing_defaults(settings=settings)
        with _repository(settings) as repository:
            service = OrchestratorService(
                repository=repository,
                workdir_root=settings.orchestrator.workdir_root,
                routing_defaults=routing_defaults,
            )
            task = service.enqueue_demo_task(
                EnqueueDemoTask(
                    task_type=command.task_type,
                    prompt=command.prompt,
                    source_ids=command.source_ids,
                    priority=command.priority,
                    max_attempts=command.max_attempts,
                    timeout_seconds=command.timeout_seconds,
                    agent=command.agent,
                    model_profile=command.model_profile,
                    model=command.model,
                ),
            )

        return [
            "Task enqueued: "
            f"task_id={task.task_id} type={task.task_type} status={task.status.value}",
            f"Manifest: {task.input_manifest_path}",
        ]

    def run_worker(self, command: LlmWorkerCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = _routing_defaults(settings=settings)
        with _repository(settings) as repository:
            worker = OrchestratorWorker(
                repository=repository,
                backend=CliAgentBackend(),
                routing_defaults=routing_defaults,
                worker_id=settings.orchestrator.worker_id,
                poll_interval_seconds=settings.orchestrator.poll_interval_seconds,
                retry_base_seconds=settings.orchestrator.retry_base_seconds,
                retry_max_seconds=settings.orchestrator.retry_max_seconds,
            )
            summary = (
                worker.run_once() if command.once else worker.run_loop(max_tasks=command.max_tasks)
            )

        return [
            "Worker summary: "
            f"processed={summary.processed} succeeded={summary.succeeded} "
            f"failed={summary.failed} retried={summary.retried} "
            f"timeouts={summary.timeouts} idle_polls={summary.idle_polls}",
        ]

    def list_tasks(self, command: LlmListTasksCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        status_filter = _parse_status(command.status)
        with _repository(settings) as repository:
            tasks = repository.list_tasks(status=status_filter, limit=command.limit)

        lines = [f"Tasks: {len(tasks)}"]
        for task in tasks:
            lines.append(
                f"  {task.task_id} type={task.task_type} status={task.status.value} "
                f"priority={task.priority} attempt={task.attempt}/{task.max_attempts} "
                f"run_after={task.run_after.isoformat()}",
            )
        return lines

    def inspect_task(self, command: LlmInspectTaskCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            details = repository.get_task_details(task_id=command.task_id)
        if details is None:
            return [f"Task not found: {command.task_id}"]

        task = details.task
        lines = [
            f"Task: {task.task_id}",
            f"Type: {task.task_type}",
            f"Status: {task.status.value}",
            f"Attempt: {task.attempt}/{task.max_attempts}",
            f"Failure class: {task.failure_class.value if task.failure_class else '-'}",
            f"Error: {task.error_summary or '-'}",
            f"Manifest: {task.input_manifest_path}",
            f"Output: {task.output_path or '-'}",
            f"Events: {len(details.events)}",
        ]
        for event in details.events:
            lines.append(
                f"  {event.created_at.isoformat()} {event.event_type} "
                f"{event.status_from.value if event.status_from else '-'} -> "
                f"{event.status_to.value if event.status_to else '-'}",
            )
        return lines

    def retry_task(self, command: LlmMutateTaskCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            repository.retry_task(task_id=command.task_id)
        return [f"Task re-queued: {command.task_id}"]

    def cancel_task(self, command: LlmMutateTaskCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            repository.cancel_task(task_id=command.task_id)
        return [f"Task canceled: {command.task_id}"]

    def smoke(self, command: LlmSmokeCommand) -> LlmSmokeResult:  # noqa: C901
        settings = Settings.from_env()
        try:
            routing_defaults = _routing_defaults(settings=settings)
            default_agent = routing_defaults.default_agent
        except ValueError as error:
            return LlmSmokeResult(
                lines=[
                    "LLM smoke check:",
                    str(error),
                ],
                success=False,
            )
        if command.model_profile not in {"fast", "quality"}:
            return LlmSmokeResult(
                lines=[
                    "LLM smoke check:",
                    f"Unsupported model profile: {command.model_profile!r}",
                ],
                success=False,
            )
        selected = set(command.agents) if command.agents else {default_agent}
        if not selected.issubset(set(SUPPORTED_AGENTS)):
            return LlmSmokeResult(
                lines=[
                    "LLM smoke check:",
                    f"Unsupported agent(s): {', '.join(sorted(selected))}",
                ],
                success=False,
            )

        command_templates = {
            "claude": command.claude_command
            or os.getenv("NEWS_RECAP_LLM_SMOKE_CLAUDE_COMMAND")
            or settings.orchestrator.claude_command_template,
            "codex": command.codex_command
            or os.getenv("NEWS_RECAP_LLM_SMOKE_CODEX_COMMAND")
            or settings.orchestrator.codex_command_template,
            "gemini": command.gemini_command
            or os.getenv("NEWS_RECAP_LLM_SMOKE_GEMINI_COMMAND")
            or settings.orchestrator.gemini_command_template,
        }
        selected_models: dict[str, str] = {}
        for agent in selected:
            if command.model is not None:
                selected_models[agent] = command.model
            else:
                selected_models[agent] = routing_defaults.models[agent][command.model_profile]
        specs = [
            AgentSmokeSpec(
                agent=agent,
                executable=agent,
                model=selected_models[agent],
                command_template=command_templates.get(agent),
            )
            for agent in ("claude", "codex", "gemini")
            if agent in selected
        ]
        results = run_smoke_checks(
            specs=specs,
            prompt=command.prompt,
            expect_substring=command.expect_substring,
            timeout_seconds=command.timeout_seconds,
        )

        lines = [
            "LLM smoke check:",
            f"default_agent={default_agent}",
            f"model_profile={command.model_profile}",
            f"model_override={command.model!r}",
            f"prompt={command.prompt!r}",
            f"expect_substring={command.expect_substring!r}",
            f"timeout_seconds={command.timeout_seconds}",
        ]
        success = True
        for result in results:
            run_state = "ok" if result.run_ok else ("skipped" if result.skipped_run else "failed")
            line = (
                f"  agent={result.agent} available={'yes' if result.available else 'no'} "
                f"model={selected_models[result.agent]} "
                f"probe={'ok' if result.probe_ok else 'failed'} run={run_state}"
            )
            if result.error:
                line += f" error={result.error}"
            lines.append(line)
            if result.stdout_preview:
                lines.append(f"    stdout={result.stdout_preview}")
            if result.stderr_preview:
                lines.append(f"    stderr={result.stderr_preview}")
            if not (result.available and result.probe_ok and result.run_ok):
                success = False

        lines.append(f"Smoke status: {'passed' if success else 'failed'}")
        if not success:
            lines.append(
                "Hint: configure run commands with "
                "NEWS_RECAP_LLM_SMOKE_{CLAUDE|CODEX|GEMINI}_COMMAND "
                "or --claude-command/--codex-command/--gemini-command.",
            )
        return LlmSmokeResult(lines=lines, success=success)


def _parse_status(value: str | None) -> LlmTaskStatus | None:
    if value is None:
        return None
    return LlmTaskStatus(value.strip().lower())


def _routing_defaults(*, settings: Settings) -> RoutingDefaults:
    return RoutingDefaults.from_settings(settings.orchestrator)


@contextmanager
def _repository(settings: Settings) -> Iterator[OrchestratorRepository]:
    repository = OrchestratorRepository(
        db_path=settings.db_path,
        user_id=settings.user_context.user_id,
        user_name=settings.user_context.user_name,
    )
    repository.init_schema()
    try:
        yield repository
    finally:
        repository.close()
