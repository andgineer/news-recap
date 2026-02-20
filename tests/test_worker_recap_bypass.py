"""Tests that _persist_success skips citation snapshots for recap_ tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_recap.orchestrator.backend.base import BackendRunResult
from news_recap.orchestrator.contracts import ArticleIndexEntry
from news_recap.orchestrator.models import LlmTaskStatus, LlmTaskView
from news_recap.orchestrator.routing import FrozenRouting
from news_recap.orchestrator.worker import LoadInputsResult, OrchestratorWorker, WorkerRunSummary


def _make_task(task_type: str) -> LlmTaskView:
    now = datetime.now(tz=timezone.utc)
    return LlmTaskView(
        task_id="test-task-001",
        user_id="user1",
        task_type=task_type,
        priority=100,
        status=LlmTaskStatus.RUNNING,
        attempt=1,
        max_attempts=3,
        timeout_seconds=600,
        run_after=now,
        started_at=now,
        heartbeat_at=now,
        finished_at=None,
        failure_class=None,
        last_exit_code=None,
        repair_attempted_at=None,
        worker_id="test-worker",
        input_manifest_path="/tmp/manifest.json",
        output_path="/tmp/output.json",
        error_summary=None,
        created_at=now,
        updated_at=now,
    )


def _make_routing() -> FrozenRouting:
    return FrozenRouting(
        schema_version=1,
        agent="codex",
        profile="fast",
        model="gpt-5-codex-mini",
        command_template="codex exec {prompt}",
        resolved_at="2026-01-01T00:00:00Z",
        resolved_by="test",
    )


def _make_execution(tmp_path: Path) -> BackendRunResult:
    stdout = tmp_path / "agent_stdout.log"
    stderr = tmp_path / "agent_stderr.log"
    stdout.write_text("")
    stderr.write_text("")
    return BackendRunResult(exit_code=0, timed_out=False, stdout_path=stdout, stderr_path=stderr)


def _make_loaded(tmp_path: Path) -> LoadInputsResult:
    output = tmp_path / "output" / "agent_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('{"articles": []}')
    return LoadInputsResult(
        ok=True,
        manifest_path=tmp_path / "meta" / "task_manifest.json",
        manifest=None,
        task_input=None,
        article_entries=[
            ArticleIndexEntry(
                source_id="article:1",
                title="Test",
                url="https://example.com",
                source="test",
                published_at="2026-01-01",
            )
        ],
        allowed_source_ids={"article:1"},
        error_summary=None,
        failure_class=None,
        attempt_failure_code=None,
        output_path=output,
    )


@pytest.fixture
def worker():
    repo = MagicMock()
    repo.complete_task.return_value = True
    backend = MagicMock()
    routing_defaults = MagicMock()
    w = OrchestratorWorker(
        repository=repo,
        backend=backend,
        routing_defaults=routing_defaults,
        worker_id="test-worker",
    )
    return w


class TestRecapCitationBypass:
    def test_recap_task_skips_citation_snapshots(self, worker, tmp_path):
        """recap_ tasks must NOT call _build_output_citation_snapshots."""

        task = _make_task("recap_classify")
        summary = WorkerRunSummary()

        with patch.object(
            worker, "_build_output_citation_snapshots", side_effect=AssertionError("should not be called")
        ), patch.object(worker, "_finalize_attempt"):
            worker._persist_success(
                task=task,
                execution=_make_execution(tmp_path),
                routing=_make_routing(),
                loaded=_make_loaded(tmp_path),
                validation_payload={"articles": [{"article_id": "a1", "decision": "keep"}]},
                task_input_metadata={},
                summary=summary,
                attempt_failure_code="",
            )

        assert summary.succeeded == 1
        worker.repository.complete_task.assert_called_once()
        call_kwargs = worker.repository.complete_task.call_args
        assert call_kwargs.kwargs.get("citations") == [] or call_kwargs[1].get("citations") == []
        assert call_kwargs.kwargs.get("user_output") is None or call_kwargs[1].get("user_output") is None

    def test_non_recap_task_builds_citation_snapshots(self, worker, tmp_path):
        """Standard tasks must call _build_output_citation_snapshots."""

        task = _make_task("highlights")
        summary = WorkerRunSummary()
        mock_citations = [MagicMock()]

        with patch.object(
            worker, "_build_output_citation_snapshots", return_value=mock_citations
        ) as mock_build, patch.object(worker, "_finalize_attempt"):
            worker._persist_success(
                task=task,
                execution=_make_execution(tmp_path),
                routing=_make_routing(),
                loaded=_make_loaded(tmp_path),
                validation_payload={"blocks": [{"text": "hello", "source_ids": ["article:1"]}]},
                task_input_metadata={},
                summary=summary,
                attempt_failure_code="",
            )

        mock_build.assert_called_once()
        assert summary.succeeded == 1

    def test_recap_enrich_full_also_skips(self, worker, tmp_path):
        """All recap_ prefixed types should skip citation snapshots."""

        for task_type in ("recap_enrich", "recap_group", "recap_enrich_full", "recap_synthesize", "recap_compose"):
            task = _make_task(task_type)
            summary = WorkerRunSummary()

            with patch.object(
                worker, "_build_output_citation_snapshots", side_effect=AssertionError("should not be called")
            ), patch.object(worker, "_finalize_attempt"):
                worker._persist_success(
                    task=task,
                    execution=_make_execution(tmp_path),
                    routing=_make_routing(),
                    loaded=_make_loaded(tmp_path),
                    validation_payload={"enriched": []},
                    task_input_metadata={},
                    summary=summary,
                    attempt_failure_code="",
                )

            assert summary.succeeded == 1, f"Failed for {task_type}"
