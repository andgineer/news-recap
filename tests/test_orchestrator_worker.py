from __future__ import annotations

import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import allure

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import NormalizedArticle
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.orchestrator.backend import CliAgentBackend
from news_recap.orchestrator.contracts import read_manifest
from news_recap.orchestrator.models import LlmTaskStatus
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import RoutingDefaults
from news_recap.orchestrator.services import EnqueueDemoTask, OrchestratorService
from news_recap.orchestrator.worker import OrchestratorWorker

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Task Queue Reliability"),
]


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


def _seed_source_id(db_path: Path, *, external_id: str = "seed-1") -> str:
    repo = SQLiteRepository(db_path)
    repo.init_schema()
    run_id = repo.start_run(source="rss")
    url = f"https://example.com/news/{external_id}"
    canonical = canonicalize_url(url)
    result = repo.upsert_article(
        article=NormalizedArticle(
            source_name="rss",
            external_id=external_id,
            url=url,
            url_canonical=canonical,
            url_hash=url_hash(canonical),
            title=f"Seed {external_id}",
            source_domain=extract_domain(canonical),
            published_at=datetime(2026, 2, 18, 12, 0, tzinfo=UTC),
            language_detected="en",
            content_raw="seed",
            summary_raw=None,
            is_full_content=True,
            needs_enrichment=False,
            clean_text="seed",
            clean_text_chars=4,
            is_truncated=False,
        ),
        run_id=run_id,
    )
    repo.close()
    return f"article:{result.article_id}"


def test_worker_executes_task_successfully_with_echo_agent(tmp_path: Path) -> None:
    db_path = tmp_path / "worker.db"
    source_id = _seed_source_id(db_path, external_id="worker-success")
    repository = OrchestratorRepository(db_path)
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
            source_ids=(source_id,),
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
    assert any(event.event_type == "first_pass_validation_passed" for event in details.events)
    assert details.task.output_path is not None
    attempts = repository.list_task_attempts(task_id=task.task_id)
    assert len(attempts) == 1
    assert attempts[0].status == "succeeded"
    assert attempts[0].attempt_failure_code == "completed"
    citations = repository.list_output_citations(task_id=task.task_id)
    assert len(citations) == 1
    assert citations[0].source_id == source_id
    repository.close()


def test_worker_recovers_missing_output_file_from_stdout(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-stdout-recovery.db"
    source_id = _seed_source_id(db_path, external_id="worker-stdout-recovery")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    stdout_only_agent = tmp_path / "stdout_only_agent.py"
    stdout_only_agent.write_text(
        """
print("Recovered from stdout parser")
""".strip(),
        "utf-8",
    )
    command_template = f"{sys.executable} {stdout_only_agent}"
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Recover from stdout.",
            source_ids=(source_id,),
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

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.SUCCEEDED
    assert any(event.event_type == "stdout_parser_recovered" for event in details.events)

    attempts = repository.list_task_attempts(task_id=task.task_id)
    assert len(attempts) == 1
    assert attempts[0].attempt_failure_code == "stdout_parser_recovered"
    assert attempts[0].output_chars is not None
    assert attempts[0].output_chars > 0
    repository.close()


def test_worker_extracts_token_usage_into_attempt_telemetry(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-usage.db"
    source_id = _seed_source_id(db_path, external_id="worker-usage")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    usage_agent = tmp_path / "usage_agent.py"
    usage_agent.write_text(
        """
import argparse
import sys
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest, read_articles_index

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args = parser.parse_args()
manifest = read_manifest(Path(args.task_manifest))
articles = read_articles_index(Path(manifest.articles_index_path))
source_id = articles[0].source_id if articles else "article:missing"
Path(manifest.output_result_path).write_text(
    '{"blocks":[{"text":"ok","source_ids":["' + source_id + '"]}]}',
    "utf-8",
)
sys.stderr.write("tokens used\\n12,345\\n")
""".strip(),
        "utf-8",
    )
    command_template = f"{sys.executable} {usage_agent} --task-manifest {{task_manifest}}"
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Collect usage.",
            source_ids=(source_id,),
        ),
    )

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    summary = worker.run_once()
    assert summary.succeeded == 1

    attempts = repository.list_task_attempts(task_id=task.task_id)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.total_tokens == 12345
    assert attempt.usage_status == "reported"
    assert attempt.usage_source in {"agent_stderr", "agent_stdout"}
    assert attempt.usage_parser_version == "v1"
    repository.close()


def test_worker_marks_source_mapping_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-invalid.db"
    source_id = _seed_source_id(db_path, external_id="worker-invalid")
    repository = OrchestratorRepository(db_path)
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
            source_ids=(source_id,),
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
    assert any(event.event_type == "first_pass_validation_failed" for event in details.events)
    repository.close()


def test_worker_does_not_override_canceled_task_with_success(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-cancel.db"
    source_id = _seed_source_id(db_path, external_id="worker-cancel")
    repository = OrchestratorRepository(db_path)
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
            source_ids=(source_id,),
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
    citations = repository.list_output_citations(task_id=task.task_id)
    assert citations == []
    event_types = [event.event_type for event in final_details.events]
    assert "canceled" in event_types
    assert "succeeded" not in event_types
    repository.close()


def test_worker_applies_routing_fallback_for_legacy_task(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-legacy-routing.db"
    source_id = _seed_source_id(db_path, external_id="worker-legacy")
    repository = OrchestratorRepository(db_path)
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
            source_ids=(source_id,),
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


def test_enqueue_demo_task_requires_user_scoped_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-no-sources.db"
    repository = OrchestratorRepository(db_path)
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

    try:
        service.enqueue_demo_task(
            EnqueueDemoTask(
                task_type="highlights",
                prompt="No sources available.",
                source_ids=(),
            ),
        )
    except ValueError as error:
        assert "No user-scoped articles available" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected enqueue to fail without user-scoped sources.")
    repository.close()


def test_enqueue_demo_task_rejects_unknown_user_source_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-unknown-source.db"
    _seed_source_id(db_path, external_id="worker-known")
    repository = OrchestratorRepository(db_path)
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

    try:
        service.enqueue_demo_task(
            EnqueueDemoTask(
                task_type="highlights",
                prompt="Unknown source id.",
                source_ids=("article:missing",),
            ),
        )
    except ValueError as error:
        assert "Unknown source_ids for current user scope" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected enqueue to fail for unknown source id.")
    repository.close()
