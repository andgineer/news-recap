from __future__ import annotations

import json
import threading
import time
import sys
from pathlib import Path

from news_recap.orchestrator.backend import CliAgentBackend
from news_recap.orchestrator.contracts import read_manifest
from news_recap.orchestrator.models import LlmTaskStatus
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import RoutingDefaults
from news_recap.orchestrator.services import EnqueueDemoTask, OrchestratorService
from news_recap.orchestrator.worker import OrchestratorWorker


def _routing_defaults(command_template: str) -> RoutingDefaults:
    return RoutingDefaults(
        default_agent="codex",
        task_type_profile_map={
            "highlights": "fast",
        },
        command_templates={
            "claude": command_template,
            "codex": command_template,
            "gemini": command_template,
        },
        models={
            "claude": {"fast": "claude-fast", "quality": "claude-quality"},
            "codex": {"fast": "codex-fast", "quality": "codex-quality"},
            "gemini": {"fast": "gemini-fast", "quality": "gemini-quality"},
        },
    )


def test_worker_executes_task_successfully_with_echo_agent(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "worker.db")
    repository.init_schema()
    command_template = (
        f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
        "--task-manifest {task_manifest}"
    )
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Top stories today.",
            source_ids=("article:1",),
        ),
    )
    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    summary = worker.run_once()
    assert summary.processed == 1
    assert summary.succeeded == 1
    assert summary.failed == 0

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.SUCCEEDED
    assert details.task.output_path is not None
    repository.close()


def test_worker_marks_source_mapping_failure(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "worker-invalid.db")
    repository.init_schema()

    invalid_agent = tmp_path / "invalid_agent.py"
    invalid_agent.write_text(
        """
import argparse
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args = parser.parse_args()
manifest = read_manifest(Path(args.task_manifest))
Path(manifest.output_result_path).write_text('{"blocks":[{"text":"bad","source_ids":[]}]}', "utf-8")
""".strip(),
        "utf-8",
    )

    command_template = f"{sys.executable} {invalid_agent} --task-manifest {{task_manifest}}"
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Check mapping.",
            source_ids=("article:1",),
        ),
    )
    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    summary = worker.run_once()
    assert summary.processed == 1
    assert summary.failed == 1

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.FAILED
    assert details.task.failure_class is not None
    assert details.task.failure_class.value == "source_mapping_failed"
    repository.close()


def test_worker_does_not_override_canceled_task_with_success(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "worker-cancel.db")
    repository.init_schema()

    slow_agent = tmp_path / "slow_agent.py"
    slow_agent.write_text(
        """
import argparse
import time
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest, read_articles_index

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args = parser.parse_args()
manifest = read_manifest(Path(args.task_manifest))
articles = read_articles_index(Path(manifest.articles_index_path))
time.sleep(2.0)
source_id = articles[0].source_id if articles else "source:demo"
Path(manifest.output_result_path).write_text(
    '{"blocks":[{"text":"ok","source_ids":["' + source_id + '"]}]}',
    "utf-8",
)
""".strip(),
        "utf-8",
    )

    command_template = f"{sys.executable} {slow_agent} --task-manifest {{task_manifest}}"
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Cancel me.",
            source_ids=("article:1",),
        ),
    )
    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )

    thread = threading.Thread(target=worker.run_once)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        details = repository.get_task_details(task_id=task.task_id)
        if details is not None and details.task.status == LlmTaskStatus.RUNNING:
            break
        time.sleep(0.02)
    else:  # pragma: no cover - defensive
        raise AssertionError("Task never reached running state before cancel.")

    cancel_applied = False
    cancel_deadline = time.time() + 2
    while time.time() < cancel_deadline:
        try:
            repository.cancel_task(task_id=task.task_id)
            cancel_applied = True
            break
        except RuntimeError as error:
            if "Task state changed concurrently while canceling" in str(error):
                time.sleep(0.02)
                continue
            raise
    assert cancel_applied
    thread.join(timeout=5)
    assert thread.is_alive() is False

    final_details = repository.get_task_details(task_id=task.task_id)
    assert final_details is not None
    assert final_details.task.status == LlmTaskStatus.CANCELED
    event_types = [event.event_type for event in final_details.events]
    assert "canceled" in event_types
    assert "succeeded" not in event_types
    repository.close()


def test_worker_applies_routing_fallback_for_legacy_task(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "worker-legacy-routing.db")
    repository.init_schema()
    command_template = (
        f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
        "--task-manifest {task_manifest}"
    )
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Legacy routing fallback.",
            source_ids=("article:1",),
        ),
    )

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    manifest = read_manifest(Path(details.task.input_manifest_path))
    task_input_path = Path(manifest.task_input_path)
    task_input = json.loads(task_input_path.read_text("utf-8"))
    task_input["metadata"] = {}
    task_input_path.write_text(json.dumps(task_input, ensure_ascii=False, indent=2), "utf-8")

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    summary = worker.run_once()
    assert summary.succeeded == 1

    final_details = repository.get_task_details(task_id=task.task_id)
    assert final_details is not None
    assert any(event.event_type == "routing_fallback_applied" for event in final_details.events)
    repository.close()
