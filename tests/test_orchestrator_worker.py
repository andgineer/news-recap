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
        "--task-manifest {task_manifest} {prompt}"
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


def test_worker_recovers_invalid_output_file_from_stdout(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-stdout-recovery.db"
    source_id = _seed_source_id(db_path, external_id="worker-stdout-recovery")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    stdout_only_agent = tmp_path / "stdout_only_agent.py"
    stdout_only_agent.write_text(
        """
import argparse
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
Path(manifest.output_result_path).write_text('{"blocks":[', "utf-8")
print("Recovered from stdout parser")
""".strip(),
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {stdout_only_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Recover from stdout.",
            source_ids=(source_id,),
        ),
    )

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        backend_capability_mode="stdout_parser_fallback",
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
args, _ = parser.parse_known_args()
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
    command_template = (
        f"{sys.executable} {usage_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
Path(manifest.output_result_path).write_text('{"blocks":[{"text":"bad","source_ids":[]}]}', "utf-8")
""".strip(),
        "utf-8",
    )

    command_template = (
        f"{sys.executable} {invalid_agent} --task-manifest {{task_manifest}} {{prompt}}"
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


def test_worker_fails_fast_when_command_template_has_no_prompt_placeholder(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-missing-prompt.db"
    source_id = _seed_source_id(db_path, external_id="worker-missing-prompt")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    command_template = "echo {task_manifest}"
    routing_defaults = _routing_defaults(command_template)
    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Should fail fast.",
            source_ids=(source_id,),
            max_attempts=1,
        ),
    )
    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    summary = worker.run_once()
    assert summary.failed == 1

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.FAILED
    assert details.task.failure_class is not None
    assert details.task.failure_class.value == "backend_non_retryable"
    assert details.task.error_summary is not None
    assert "must include {prompt}" in details.task.error_summary
    repository.close()


def test_worker_stdout_recovers_when_output_file_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-missing-output-recover.db"
    source_id = _seed_source_id(db_path, external_id="worker-missing-output-recover")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    missing_output_agent = tmp_path / "missing_output_agent.py"
    missing_output_agent.write_text(
        """
print("Parser candidate text that should auto-recover missing output file.")
""".strip(),
        "utf-8",
    )
    command_template = f"{sys.executable} {missing_output_agent} {{task_manifest}} {{prompt}}"
    routing_defaults = _routing_defaults(command_template)
    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Missing output file should recover from stdout.",
            source_ids=(source_id,),
        ),
    )
    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        backend_capability_mode="stdout_parser_fallback",
    )
    summary = worker.run_once()
    assert summary.succeeded == 1
    assert summary.failed == 0

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.SUCCEEDED
    assert details.task.failure_class is None
    event_types = [event.event_type for event in details.events]
    assert "stdout_parser_recovered" in event_types
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
args, _ = parser.parse_known_args()
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

    command_template = f"{sys.executable} {slow_agent} --task-manifest {{task_manifest}} {{prompt}}"
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


def test_worker_graceful_stop_emits_shutdown_events_and_stops_new_claims(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-graceful-stop.db"
    source_id = _seed_source_id(db_path, external_id="worker-graceful-stop")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    slow_agent = tmp_path / "slow_graceful_agent.py"
    slow_agent.write_text(
        """
import argparse
import time
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest, read_articles_index

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
articles = read_articles_index(Path(manifest.articles_index_path))
time.sleep(1.0)
source_id = articles[0].source_id if articles else "source:demo"
Path(manifest.output_result_path).write_text(
    '{"blocks":[{"text":"ok","source_ids":["' + source_id + '"]}]}',
    "utf-8",
)
""".strip(),
        "utf-8",
    )

    command_template = f"{sys.executable} {slow_agent} --task-manifest {{task_manifest}} {{prompt}}"
    routing_defaults = _routing_defaults(command_template)

    service = OrchestratorService(
        repository=repository,
        workdir_root=tmp_path / "workdir",
        routing_defaults=routing_defaults,
    )
    first_task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="First task.",
            source_ids=(source_id,),
        ),
    )
    second_task = service.enqueue_demo_task(
        EnqueueDemoTask(
            task_type="highlights",
            prompt="Second task should stay queued.",
            source_ids=(source_id,),
        ),
    )

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        poll_interval_seconds=0.0,
    )

    worker_thread = threading.Thread(target=worker.run_loop)
    worker_thread.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        details = repository.get_task_details(task_id=first_task.task_id)
        if details is not None and details.task.status == LlmTaskStatus.RUNNING:
            break
        time.sleep(0.02)
    else:  # pragma: no cover - defensive
        raise AssertionError("First task never reached running state before shutdown request.")

    worker._request_stop(signal_name="SIGTERM")
    worker_thread.join(timeout=10)
    assert worker_thread.is_alive() is False

    first_details = repository.get_task_details(task_id=first_task.task_id)
    assert first_details is not None
    first_events = [event.event_type for event in first_details.events]
    assert "shutdown_requested" in first_events
    assert "shutdown_completed" in first_events

    second_details = repository.get_task_details(task_id=second_task.task_id)
    assert second_details is not None
    assert second_details.task.status == LlmTaskStatus.QUEUED
    repository.close()


def test_worker_graceful_shutdown_timeout_interrupts_long_running_backend(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-graceful-timeout.db"
    source_id = _seed_source_id(db_path, external_id="worker-graceful-timeout")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    very_slow_agent = tmp_path / "very_slow_agent.py"
    very_slow_agent.write_text(
        """
import argparse
import time
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
time.sleep(10.0)
Path(manifest.output_result_path).write_text("{}", "utf-8")
""".strip(),
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {very_slow_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Long task interrupted by graceful shutdown.",
            source_ids=(source_id,),
            timeout_seconds=30,
            max_attempts=1,
        ),
    )

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        poll_interval_seconds=0.0,
        graceful_shutdown_seconds=1,
    )
    started = time.monotonic()
    worker_thread = threading.Thread(target=worker.run_loop)
    worker_thread.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        details = repository.get_task_details(task_id=task.task_id)
        if details is not None and details.task.status == LlmTaskStatus.RUNNING:
            break
        time.sleep(0.02)
    else:  # pragma: no cover - defensive
        raise AssertionError("Task did not enter running state before stop request.")

    worker._request_stop(signal_name="SIGTERM")
    worker_thread.join(timeout=5)
    elapsed = time.monotonic() - started
    assert worker_thread.is_alive() is False
    assert elapsed < 7.0

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.TIMEOUT
    repository.close()


def test_worker_applies_routing_fallback_for_legacy_task(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-legacy-routing.db"
    source_id = _seed_source_id(db_path, external_id="worker-legacy")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()
    command_template = (
        f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
        "--task-manifest {task_manifest} {prompt}"
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


def test_worker_timeout_schedules_retry(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-timeout-retry.db"
    source_id = _seed_source_id(db_path, external_id="worker-timeout-retry")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    timeout_agent = tmp_path / "timeout_agent.py"
    timeout_agent.write_text(
        """
import argparse
import time
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
time.sleep(2.0)
Path(manifest.output_result_path).write_text("{}", "utf-8")
""".strip(),
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {timeout_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Timeout and retry.",
            source_ids=(source_id,),
            max_attempts=2,
            timeout_seconds=1,
        ),
    )

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        retry_base_seconds=0,
        retry_max_seconds=0,
    )
    summary = worker.run_once()
    assert summary.processed == 1
    assert summary.retried == 1
    assert summary.failed == 0

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.QUEUED
    assert any(event.event_type == "retry_scheduled" for event in details.events)
    repository.close()


def test_worker_transient_retry_then_success(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-transient-retry.db"
    source_id = _seed_source_id(db_path, external_id="worker-transient-retry")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    transient_agent = tmp_path / "transient_agent.py"
    transient_agent.write_text(
        """
import argparse
import sys
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest, read_articles_index

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
state_path = Path(manifest.workdir) / "state.txt"
if not state_path.exists():
    state_path.write_text("1", "utf-8")
    sys.stderr.write("HTTP 429 too many requests\\n")
    raise SystemExit(1)

articles = read_articles_index(Path(manifest.articles_index_path))
source_id = articles[0].source_id if articles else "article:missing"
Path(manifest.output_result_path).write_text(
    '{"blocks":[{"text":"ok","source_ids":["' + source_id + '"]}]}',
    "utf-8",
)
""".strip(),
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {transient_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Transient then success.",
            source_ids=(source_id,),
            max_attempts=2,
            timeout_seconds=60,
        ),
    )
    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        retry_base_seconds=0,
        retry_max_seconds=0,
    )

    first = worker.run_once()
    assert first.retried == 1
    second = worker.run_once()
    assert second.succeeded == 1

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.SUCCEEDED
    assert any(event.event_type == "retry_scheduled" for event in details.events)
    assert any(event.event_type == "succeeded" for event in details.events)
    repository.close()


def test_worker_repair_path_recovers_on_second_backend_call(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-repair-success.db"
    source_id = _seed_source_id(db_path, external_id="worker-repair-success")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    repair_agent = tmp_path / "repair_agent.py"
    repair_agent.write_text(
        """
import argparse
import os
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest, read_articles_index

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
if os.getenv("NEWS_RECAP_REPAIR_MODE", "0") != "1":
    Path(manifest.output_result_path).write_text('{"blocks":[{"text":"bad","source_ids":[]}]}', "utf-8")
    raise SystemExit(0)

articles = read_articles_index(Path(manifest.articles_index_path))
source_id = articles[0].source_id if articles else "article:missing"
Path(manifest.output_result_path).write_text(
    '{"blocks":[{"text":"repaired","source_ids":["' + source_id + '"]}]}',
    "utf-8",
)
""".strip(),
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {repair_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Repair path test.",
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
    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert any(event.event_type == "repair_attempted" for event in details.events)
    attempts = repository.list_task_attempts(task_id=task.task_id)
    assert attempts[0].attempt_failure_code == "repair_recovered"
    repository.close()


def test_worker_skips_repair_when_already_repaired_in_attempt(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-repair-already.db"
    source_id = _seed_source_id(db_path, external_id="worker-repair-already")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    no_repair_agent = tmp_path / "no_repair_agent.py"
    no_repair_agent.write_text(
        """
import argparse
import os
from pathlib import Path
from news_recap.orchestrator.contracts import read_manifest, read_articles_index

parser = argparse.ArgumentParser()
parser.add_argument("--task-manifest", required=True)
args, _ = parser.parse_known_args()
manifest = read_manifest(Path(args.task_manifest))
marker = Path(manifest.workdir) / "repair_mode_called.txt"
if os.getenv("NEWS_RECAP_REPAIR_MODE", "0") == "1":
    marker.write_text("called", "utf-8")
    articles = read_articles_index(Path(manifest.articles_index_path))
    source_id = articles[0].source_id if articles else "article:missing"
    Path(manifest.output_result_path).write_text(
        '{"blocks":[{"text":"repair","source_ids":["' + source_id + '"]}]}',
        "utf-8",
    )
else:
    Path(manifest.output_result_path).write_text('{"blocks":[{"text":"bad","source_ids":[]}]}', "utf-8")
""".strip(),
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {no_repair_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Already repaired marker.",
            source_ids=(source_id,),
        ),
    )

    repository._connection.execute(
        "UPDATE llm_tasks SET repair_attempted_at = ? WHERE task_id = ?",
        (datetime.now(tz=UTC).replace(tzinfo=None).isoformat(sep=" "), task.task_id),
    )
    repository._connection.commit()

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    summary = worker.run_once()
    assert summary.failed == 1

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.FAILED
    manifest = read_manifest(Path(details.task.input_manifest_path))
    repair_marker = Path(manifest.workdir) / "repair_mode_called.txt"
    assert repair_marker.exists() is False
    repository.close()


def test_enqueue_demo_task_requires_user_scoped_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-no-sources.db"
    repository = OrchestratorRepository(db_path)
    repository.init_schema()
    command_template = (
        f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
        "--task-manifest {task_manifest} {prompt}"
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
        "--task-manifest {task_manifest} {prompt}"
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


def test_worker_finalizes_attempt_before_completing_task(tmp_path: Path) -> None:
    """Attempt telemetry should be finalized before task status transitions to SUCCEEDED."""
    db_path = tmp_path / "worker-finalize-order.db"
    source_id = _seed_source_id(db_path, external_id="worker-finalize-order")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    command_template = (
        f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
        "--task-manifest {task_manifest} {prompt}"
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
            prompt="Test finalization ordering.",
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
    assert attempt.finished_at is not None
    assert attempt.status == "succeeded"
    assert attempt.duration_ms is not None
    assert attempt.duration_ms >= 0

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    assert details.task.status == LlmTaskStatus.SUCCEEDED
    repository.close()


def test_worker_manifest_native_mode_skips_stdout_recovery(tmp_path: Path) -> None:
    """In manifest_native mode (default), stdout parser fallback is not used."""
    db_path = tmp_path / "worker-no-parser.db"
    source_id = _seed_source_id(db_path, external_id="worker-no-parser")
    repository = OrchestratorRepository(db_path)
    repository.init_schema()

    broken_agent = tmp_path / "broken_agent.py"
    broken_agent.write_text(
        "import argparse\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--task-manifest', required=True)\n"
        "args, _ = parser.parse_known_args()\n"
        "from pathlib import Path\n"
        "from news_recap.orchestrator.contracts import read_manifest\n"
        "manifest = read_manifest(Path(args.task_manifest))\n"
        "Path(manifest.output_result_path).write_text('{\"blocks\":[', 'utf-8')\n"
        "print('stdout recovery candidate')\n",
        "utf-8",
    )
    command_template = (
        f"{sys.executable} {broken_agent} --task-manifest {{task_manifest}} {{prompt}}"
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
            prompt="Should not recover from stdout.",
            source_ids=(source_id,),
        ),
    )

    worker = OrchestratorWorker(
        repository=repository,
        backend=CliAgentBackend(),
        routing_defaults=routing_defaults,
        worker_id="test-worker",
        backend_capability_mode="manifest_native",
    )
    summary = worker.run_once()
    assert summary.succeeded == 0

    details = repository.get_task_details(task_id=task.task_id)
    assert details is not None
    event_types = [event.event_type for event in details.events]
    assert "stdout_parser_recovered" not in event_types
    repository.close()
