from __future__ import annotations

import threading
import time
import sys
from pathlib import Path

from news_recap.orchestrator.backend import CliAgentBackend
from news_recap.orchestrator.models import LlmTaskStatus
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.services import EnqueueDemoTask, OrchestratorService
from news_recap.orchestrator.worker import OrchestratorWorker


def test_worker_executes_task_successfully_with_echo_agent(tmp_path: Path) -> None:
    repository = OrchestratorRepository(tmp_path / "worker.db")
    repository.init_schema()

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
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
        backend=CliAgentBackend(f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent"),
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

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
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
        backend=CliAgentBackend(f"{sys.executable} {invalid_agent}"),
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
time.sleep(0.6)
source_id = articles[0].source_id if articles else "source:demo"
Path(manifest.output_result_path).write_text(
    '{"blocks":[{"text":"ok","source_ids":["' + source_id + '"]}]}',
    "utf-8",
)
""".strip(),
        "utf-8",
    )

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
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
        backend=CliAgentBackend(f"{sys.executable} {slow_agent}"),
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

    repository.cancel_task(task_id=task.task_id)
    thread.join(timeout=5)
    assert thread.is_alive() is False

    final_details = repository.get_task_details(task_id=task.task_id)
    assert final_details is not None
    assert final_details.task.status == LlmTaskStatus.CANCELED
    event_types = [event.event_type for event in final_details.events]
    assert "canceled" in event_types
    assert "succeeded" not in event_types
    repository.close()
