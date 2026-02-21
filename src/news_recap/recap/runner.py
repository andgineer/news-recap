"""RecapPipelineRunner — coordinator for the 6-step news digest pipeline."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from news_recap.config import Settings
from news_recap.orchestrator.backend.cli_backend import CliAgentBackend
from news_recap.orchestrator.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.orchestrator.models import (
    LlmTaskCreate,
    LlmTaskStatus,
    LlmTaskView,
    SourceCorpusEntry,
)
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import RoutingDefaults, resolve_routing_for_enqueue
from news_recap.orchestrator.workdir import TaskWorkdirManager
from news_recap.orchestrator.worker import OrchestratorWorker
from news_recap.recap.prompts import PROMPTS_BY_TASK_TYPE
from news_recap.recap.resource_loader import ResourceLoader
from news_recap.recap.schemas import SCHEMAS_BY_TASK_TYPE

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset(
    {LlmTaskStatus.SUCCEEDED, LlmTaskStatus.FAILED, LlmTaskStatus.TIMEOUT, LlmTaskStatus.CANCELED},
)

MIN_ARTICLES_FOR_SIGNIFICANT_EVENT = 2


_DEFAULT_NOT_INTERESTING = "horoscopes, medical advice, sports (except Russia), Epstein files"
_DEFAULT_INTERESTING = "Russia, Serbia, war in Ukraine"


@dataclass(slots=True)
class UserPreferences:
    """User preferences for digest composition."""

    max_headline_chars: int = 120
    interesting: str = _DEFAULT_INTERESTING
    not_interesting: str = _DEFAULT_NOT_INTERESTING
    language: str = "ru"

    def format_for_prompt(self) -> str:
        parts: list[str] = []
        if self.not_interesting:
            parts.append(f"DISCARD these topics (always trash): {self.not_interesting}")
        if self.interesting:
            parts.append(
                f"PRIORITY topics (user wants extra detail): {self.interesting}",
            )
        return "\n".join(parts) if parts else "no specific preferences"


@dataclass(slots=True)
class PipelineStepResult:
    """Result of a single pipeline step."""

    step_name: str
    task_id: str | None
    status: str
    error: str | None = None


@dataclass(slots=True)
class PipelineRunResult:
    """Result of a complete pipeline run."""

    pipeline_id: str
    business_date: date
    steps: list[PipelineStepResult] = field(default_factory=list)
    digest: dict[str, Any] | None = None
    status: str = "running"
    error: str | None = None


class RecapPipelineError(RuntimeError):
    """Pipeline step failure."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"Step {step} failed: {message}")
        self.step = step


@dataclass(slots=True)
class _WorkerSettings:
    """Tunables for the embedded worker thread."""

    poll_interval_seconds: float = 3.0
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    stale_attempt_seconds: int = 1800
    graceful_shutdown_seconds: int = 30
    backend_capability_mode: str = "manifest_native"


class RecapPipelineRunner:
    """Coordinates the 6-step news digest pipeline.

    Enqueues LLM tasks via the orchestrator, executes resource loading directly,
    and polls for task completion.  When ``embedded_worker=True`` (the default),
    an :class:`OrchestratorWorker` is started in a daemon thread so the caller
    does not need to launch a separate worker process.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        repository: OrchestratorRepository,
        workdir_root: Path,
        routing_defaults: RoutingDefaults,
        resource_loader: ResourceLoader | None = None,
        poll_interval_seconds: float = 5.0,
        max_poll_seconds: float = 1800.0,
        embedded_worker: bool = True,
        worker_settings: _WorkerSettings | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._repository = repository
        self._workdir = TaskWorkdirManager(workdir_root)
        self._routing_defaults = routing_defaults
        self._resource_loader = resource_loader
        self._poll_interval = poll_interval_seconds
        self._max_poll = max_poll_seconds
        self._embedded_worker = embedded_worker
        self._worker_settings = worker_settings or _WorkerSettings()
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._on_progress = on_progress or (lambda _msg: None)

    # -- embedded worker management -------------------------------------------

    def _start_worker(self) -> None:
        if not self._embedded_worker:
            return
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="recap-worker",
        )
        self._worker_thread.start()
        logger.info("Embedded worker thread started")

    def _stop_worker(self) -> None:
        if self._worker_thread is None:
            return
        self._worker_stop.set()
        self._worker_thread.join(timeout=15)
        self._worker_thread = None
        logger.info("Embedded worker thread stopped")

    def _worker_loop(self) -> None:
        ws = self._worker_settings
        w_repo = OrchestratorRepository(
            db_path=self._repository.db_path,
            user_id=self._repository.user_id,
            user_name=self._repository.user_name,
            sqlite_busy_timeout_ms=5_000,
        )
        w_repo.init_schema()
        try:
            worker = OrchestratorWorker(
                repository=w_repo,
                backend=CliAgentBackend(),
                routing_defaults=self._routing_defaults,
                worker_id=f"recap-embedded-{uuid4().hex[:8]}",
                poll_interval_seconds=ws.poll_interval_seconds,
                retry_base_seconds=ws.retry_base_seconds,
                retry_max_seconds=ws.retry_max_seconds,
                stale_attempt_seconds=ws.stale_attempt_seconds,
                graceful_shutdown_seconds=ws.graceful_shutdown_seconds,
                backend_capability_mode=ws.backend_capability_mode,
            )
            while not self._worker_stop.is_set():
                try:
                    summary = worker.run_once()
                    if summary.processed == 0:
                        self._worker_stop.wait(timeout=ws.poll_interval_seconds)
                except Exception:
                    logger.exception("Embedded worker error")
                    self._worker_stop.wait(timeout=5)
        finally:
            w_repo.close()

    # -- pipeline state persistence (recap_pipeline_runs/tasks) ----------------

    def _db_exec(self, sql: str, params: tuple[Any, ...]) -> None:
        """Best-effort SQL write — failures are logged, never raised."""
        try:
            conn = sqlite3.connect(str(self._repository.db_path))
            conn.execute(sql, params)
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001
            logger.debug("DB exec failed: %s", sql[:60], exc_info=True)

    def _persist_run_start(
        self,
        pipeline_id: str,
        business_date: date,
    ) -> None:
        now = datetime.now(tz=UTC).isoformat()
        self._db_exec(
            "INSERT INTO recap_pipeline_runs"
            " (pipeline_id, user_id, business_date, status,"
            " current_step, error, created_at, updated_at)"
            " VALUES (?, ?, ?, 'running', NULL, NULL, ?, ?)",
            (pipeline_id, self._repository.user_id, str(business_date), now, now),
        )

    def _persist_run_step(
        self,
        pipeline_id: str,
        step_name: str,
    ) -> None:
        now = datetime.now(tz=UTC).isoformat()
        self._db_exec(
            "UPDATE recap_pipeline_runs SET current_step = ?, updated_at = ? WHERE pipeline_id = ?",
            (step_name, now, pipeline_id),
        )

    def _persist_step_task(
        self,
        pipeline_id: str,
        step_name: str,
        task_id: str | None,
        status: str,
    ) -> None:
        now = datetime.now(tz=UTC).isoformat()
        self._db_exec(
            "INSERT INTO recap_pipeline_tasks"
            " (pipeline_id, step_name, task_id, status, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pipeline_id, step_name, task_id, status, now),
        )

    def _persist_run_finish(
        self,
        pipeline_id: str,
        status: str,
        error: str | None,
    ) -> None:
        now = datetime.now(tz=UTC).isoformat()
        self._db_exec(
            "UPDATE recap_pipeline_runs"
            " SET status = ?, error = ?, updated_at = ?"
            " WHERE pipeline_id = ?",
            (status, error, now, pipeline_id),
        )

    def _task_results_dir(self, task_id: str) -> Path:
        return self._workdir.root_dir / task_id / "output" / "results"

    def _read_task_output(self, task_id: str) -> dict[str, Any]:
        p = self._workdir.root_dir / task_id / "output" / "agent_result.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _emit(self, msg: str) -> None:
        """Log and notify progress callback."""
        logger.info(msg)
        self._on_progress(msg)

    # -- pipeline execution ---------------------------------------------------

    _STALE_RUN_SECONDS = 1800

    def _check_no_active_run(self) -> None:
        """Prevent concurrent pipeline runs; auto-recover stale ones."""
        conn = sqlite3.connect(str(self._repository.db_path))
        try:
            row = conn.execute(
                "SELECT pipeline_id, updated_at"
                " FROM recap_pipeline_runs WHERE status = 'running'"
                " ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
            if row is None:
                return
            pipeline_id, updated_at_str = row
            updated_at = datetime.fromisoformat(updated_at_str)
            age = (datetime.now(tz=UTC) - updated_at).total_seconds()
            if age > self._STALE_RUN_SECONDS:
                now = datetime.now(tz=UTC).isoformat()
                conn.execute(
                    "UPDATE recap_pipeline_runs"
                    " SET status = 'failed', error = 'Stale run auto-recovered', updated_at = ?"
                    " WHERE pipeline_id = ?",
                    (now, pipeline_id),
                )
                conn.commit()
                logger.warning("Recovered stale pipeline run %s", pipeline_id)
                return
            raise RecapPipelineError(
                "run",
                f"Another pipeline is already running: {pipeline_id}",
            )
        finally:
            conn.close()

    def run(  # noqa: PLR0915
        self,
        *,
        business_date: date,
        preferences: UserPreferences,
        articles: list[SourceCorpusEntry],
        agent_override: str | None = None,
    ) -> PipelineRunResult:
        """Execute the full 6-step pipeline."""

        self._check_no_active_run()

        pipeline_id = str(uuid4())
        result = PipelineRunResult(pipeline_id=pipeline_id, business_date=business_date)
        pipeline_start = time.monotonic()

        self._emit(
            f"Pipeline {pipeline_id[:12]} started: {len(articles)} articles, date={business_date}",
        )
        self._persist_run_start(pipeline_id, business_date)

        self._start_worker()
        try:
            article_entries = to_article_index(articles)
            article_map = {e.source_id: e for e in article_entries}

            # Step 1: classify (one file per article, agent evaluates each in isolation)
            self._persist_run_step(pipeline_id, "recap_classify")
            per_article_files = articles_to_individual_files(articles)
            tid = self._run_llm_step(
                result=result,
                pipeline_id=pipeline_id,
                step_name="recap_classify",
                article_entries=article_entries,
                preferences=preferences,
                extra_input_files=per_article_files,
                agent_override=agent_override,
            )
            kept_ids, enrich_ids = parse_classify_out_files(
                self._task_results_dir(tid),
                articles,
            )
            kept_entries = [article_map[sid] for sid in kept_ids if sid in article_map]
            discarded = len(articles) - len(kept_ids)
            self._emit(
                f"Classify: {len(kept_ids)} kept, {discarded} discarded, "
                f"{len(enrich_ids)} need enrichment",
            )

            # Step 2: load resources (non-LLM)
            self._persist_run_step(pipeline_id, "resource_load")
            resource_entries = [article_map[sid] for sid in enrich_ids if sid in article_map]
            loaded_resources = self._load_resources(resource_entries)
            result.steps.append(
                PipelineStepResult(
                    step_name="resource_load",
                    task_id=None,
                    status="completed",
                ),
            )
            self._persist_step_task(pipeline_id, "resource_load", None, "completed")

            # Step 3: enrich
            self._persist_run_step(pipeline_id, "recap_enrich")
            tid = self._run_llm_step(
                result=result,
                pipeline_id=pipeline_id,
                step_name="recap_enrich",
                article_entries=kept_entries,
                preferences=preferences,
                extra_input_files=loaded_resources,
                agent_override=agent_override,
            )
            enriched_articles = parse_enrich_result(self._read_task_output(tid))
            self._emit(f"Enrich: {len(enriched_articles)} articles enriched")

            # Step 4.1: group
            self._persist_run_step(pipeline_id, "recap_group")
            enriched_entries = merge_enriched_into_index(kept_entries, enriched_articles)
            tid = self._run_llm_step(
                result=result,
                pipeline_id=pipeline_id,
                step_name="recap_group",
                article_entries=enriched_entries,
                preferences=preferences,
                agent_override=agent_override,
            )
            events = parse_group_result(self._read_task_output(tid))
            self._emit(f"Group: {len(events)} events identified")

            # Step 4.2: load full texts for significant events
            significant_events = select_significant_events(events)
            articles_for_full = articles_needing_full_text(significant_events, article_map)
            self._emit(
                f"Significant events: {len(significant_events)}, "
                f"articles needing full text: {len(articles_for_full)}",
            )
            self._persist_run_step(pipeline_id, "resource_load_full")
            full_resources = self._load_resources(articles_for_full)

            enrich_full_payload: dict[str, Any] = {"enriched": []}
            if full_resources:
                self._persist_run_step(pipeline_id, "recap_enrich_full")
                tid = self._run_llm_step(
                    result=result,
                    pipeline_id=pipeline_id,
                    step_name="recap_enrich_full",
                    article_entries=articles_for_full,
                    preferences=preferences,
                    extra_input_files=full_resources,
                    agent_override=agent_override,
                )
                enrich_full_payload = self._read_task_output(tid)
            enriched_full = parse_enrich_result(enrich_full_payload)

            # Step 4→5 merge: rebuild event payloads with enriched texts
            event_payloads = build_event_payloads(
                events,
                enriched_articles,
                enriched_full,
                article_map,
            )

            # Step 5: synthesize
            self._persist_run_step(pipeline_id, "recap_synthesize")
            synth_resources = events_to_resource_files(event_payloads)
            self._run_llm_step(
                result=result,
                pipeline_id=pipeline_id,
                step_name="recap_synthesize",
                article_entries=kept_entries,
                preferences=preferences,
                extra_input_files=synth_resources,
                agent_override=agent_override,
            )

            # Step 6: compose
            self._persist_run_step(pipeline_id, "recap_compose")
            compose_resources = synth_resources
            tid = self._run_llm_step(
                result=result,
                pipeline_id=pipeline_id,
                step_name="recap_compose",
                article_entries=kept_entries,
                preferences=preferences,
                extra_input_files=compose_resources,
                agent_override=agent_override,
            )

            result.digest = self._read_task_output(tid)
            result.status = "completed"
            elapsed = time.monotonic() - pipeline_start
            self._emit(f"Pipeline {pipeline_id[:12]} completed in {elapsed:.1f}s")

        except RecapPipelineError as exc:
            result.status = "failed"
            result.error = str(exc)
            logger.error("Pipeline %s failed: %s", pipeline_id, exc)
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error = f"Unexpected error: {exc}"
            logger.exception("Pipeline %s unexpected error", pipeline_id)
        finally:
            self._stop_worker()
            self._persist_run_finish(pipeline_id, result.status, result.error)

        return result

    def _run_llm_step(  # noqa: PLR0913
        self,
        *,
        result: PipelineRunResult,
        pipeline_id: str,
        step_name: str,
        article_entries: list[ArticleIndexEntry],
        preferences: UserPreferences,
        extra_input_files: dict[str, bytes | str] | None = None,
        agent_override: str | None = None,
    ) -> str:
        """Enqueue an LLM task, poll until done, return task_id."""

        step_start = time.monotonic()
        n_resources = len(extra_input_files) if extra_input_files else 0
        self._emit(
            f"[{step_name}] Starting — {len(article_entries)} articles, "
            f"{n_resources} resource files",
        )

        prompt_template = PROMPTS_BY_TASK_TYPE[step_name]
        prompt = prompt_template.format(
            preferences=preferences.format_for_prompt(),
            max_headline_chars=preferences.max_headline_chars,
        )
        schema_hint = SCHEMAS_BY_TASK_TYPE.get(step_name)

        task_id = str(uuid4())
        routing = resolve_routing_for_enqueue(
            defaults=self._routing_defaults,
            task_type=step_name,
            agent_override=agent_override,
            profile_override=None,
            model_override=None,
        )

        materialized = self._workdir.materialize(
            task_id=task_id,
            task_type=step_name,
            task_input=TaskInputContract(
                task_type=step_name,
                prompt=prompt,
                metadata={"routing": routing.to_metadata()},
            ),
            articles_index=article_entries,
            extra_input_files=extra_input_files,
            output_schema_hint=schema_hint,
        )

        if step_name == "recap_classify":
            input_dir = self._workdir.root_dir / task_id / "input"
            input_dir.joinpath("_discard.txt").write_text(
                preferences.not_interesting,
                "utf-8",
            )
            input_dir.joinpath("_priority.txt").write_text(
                preferences.interesting,
                "utf-8",
            )

        task = self._repository.enqueue_task(
            LlmTaskCreate(
                task_id=task_id,
                task_type=step_name,
                priority=100,
                max_attempts=3,
                timeout_seconds=600,
                input_manifest_path=str(materialized.manifest_path),
                output_path=materialized.manifest.output_result_path,
            ),
        )

        self._persist_step_task(pipeline_id, step_name, task.task_id, "running")
        self._emit(f"[{step_name}] Enqueued task {task.task_id[:12]}, waiting for worker…")
        completed = self._poll_until_done(task.task_id, step_name=step_name)

        step_elapsed = time.monotonic() - step_start
        if completed.status != LlmTaskStatus.SUCCEEDED:
            self._persist_step_task(pipeline_id, step_name, task.task_id, completed.status.value)
            self._emit(f"[{step_name}] Task {completed.status.value} after {step_elapsed:.1f}s")
            step_result = PipelineStepResult(
                step_name=step_name,
                task_id=task.task_id,
                status=completed.status.value,
                error=f"Task {completed.status.value}",
            )
            result.steps.append(step_result)
            raise RecapPipelineError(step_name, f"task {completed.status.value}")

        result.steps.append(
            PipelineStepResult(
                step_name=step_name,
                task_id=task.task_id,
                status="completed",
            ),
        )
        self._persist_step_task(pipeline_id, step_name, task.task_id, "completed")
        self._emit(f"[{step_name}] Completed in {step_elapsed:.1f}s")
        return task_id

    def _poll_until_done(
        self,
        task_id: str,
        *,
        step_name: str = "",
    ) -> LlmTaskView:
        """Poll repository until task reaches a terminal status."""

        start = time.monotonic()
        last_log = start
        log_interval = 15.0
        while True:
            details = self._repository.get_task_details(task_id=task_id)
            if details and details.task.status in TERMINAL_STATUSES:
                return details.task

            elapsed = time.monotonic() - start
            if elapsed > self._max_poll:
                raise RecapPipelineError(
                    "poll",
                    f"task {task_id} did not complete within {self._max_poll}s",
                )

            now = time.monotonic()
            if now - last_log >= log_interval:
                self._emit(f"[{step_name}] Waiting for task {task_id[:12]}… {elapsed:.0f}s elapsed")
                last_log = now

            time.sleep(self._poll_interval)

    def _load_resources(
        self,
        entries: list[ArticleIndexEntry],
    ) -> dict[str, bytes | str]:
        """Load full text from URLs using ResourceLoader."""

        if not entries or self._resource_loader is None:
            return {}

        total = len(entries)
        self._emit(f"Loading resources: {total} URLs to fetch")
        resources: dict[str, bytes | str] = {}
        loaded_count = 0
        failed_count = 0
        for i, entry in enumerate(entries, 1):
            if not entry.url:
                continue
            loaded = self._resource_loader.load(entry.url)
            if loaded.is_success and loaded.text:
                resource_data = {
                    "article_id": entry.source_id,
                    "title": entry.title,
                    "url": entry.url,
                    "source": entry.source,
                    "text": loaded.text,
                    "content_type": loaded.content_type,
                }
                safe_id = entry.source_id.replace(":", "_").replace("/", "_")
                resources[f"{safe_id}.json"] = json.dumps(
                    resource_data,
                    ensure_ascii=False,
                    indent=2,
                )
                loaded_count += 1
            else:
                failed_count += 1
                logger.warning(
                    "Failed to load resource for %s (%s): %s",
                    entry.source_id,
                    entry.url,
                    loaded.error,
                )
            if i % 10 == 0 or i == total:
                self._emit(
                    f"Resource loading: {i}/{total} (ok={loaded_count}, fail={failed_count})",
                )
        return resources


def to_article_index(entries: list[SourceCorpusEntry]) -> list[ArticleIndexEntry]:
    return [
        ArticleIndexEntry(
            source_id=e.source_id,
            title=e.title,
            url=e.url,
            source=e.source,
            published_at=e.published_at.isoformat(),
        )
        for e in entries
    ]


def _safe_file_id(source_id: str) -> str:
    """Turn source_id into a filesystem-safe string."""
    return source_id.replace(":", "_").replace("/", "_")


def articles_to_individual_files(
    entries: list[SourceCorpusEntry],
) -> dict[str, bytes | str]:
    """One ``{id}_in.txt`` per article containing only the headline."""
    files: dict[str, bytes | str] = {}
    for e in entries:
        fid = _safe_file_id(e.source_id)
        files[f"{fid}_in.txt"] = e.title
    return files


def parse_classify_out_files(
    results_dir: Path,
    entries: list[SourceCorpusEntry],
) -> tuple[list[str], list[str]]:
    """Read ``{id}_out.txt`` files written by the agent.

    Each file contains a single word: ``ok``, ``enrich``, or ``trash``.
    Returns (kept_ids, enrich_ids).  ``ok`` and ``enrich`` are both kept.
    """
    kept: list[str] = []
    enrich: list[str] = []
    for e in entries:
        fid = _safe_file_id(e.source_id)
        out_path = results_dir / f"{fid}_out.txt"
        if not out_path.exists():
            kept.append(e.source_id)
            continue
        verdict = out_path.read_text("utf-8").strip().lower()
        if verdict == "trash":
            continue
        kept.append(e.source_id)
        if verdict == "enrich":
            enrich.append(e.source_id)
    return kept, enrich


def parse_enrich_result(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return {article_id: {new_title, clean_text}} from enrich output."""

    enriched = payload.get("enriched", [])
    result: dict[str, dict[str, str]] = {}
    for item in enriched:
        aid = item.get("article_id", "")
        result[aid] = {
            "new_title": item.get("new_title", ""),
            "clean_text": item.get("clean_text", ""),
        }
    return result


def parse_group_result(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return events list from group output."""

    return payload.get("events", [])


def merge_enriched_into_index(
    entries: list[ArticleIndexEntry],
    enriched: dict[str, dict[str, str]],
) -> list[ArticleIndexEntry]:
    """Update article titles from enrichment pass."""

    result: list[ArticleIndexEntry] = []
    for entry in entries:
        enriched_data = enriched.get(entry.source_id)
        if enriched_data and enriched_data.get("new_title"):
            result.append(
                ArticleIndexEntry(
                    source_id=entry.source_id,
                    title=enriched_data["new_title"],
                    url=entry.url,
                    source=entry.source,
                    published_at=entry.published_at,
                ),
            )
        else:
            result.append(entry)
    return result


def select_significant_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter events to only significant ones (high/medium significance or multi-article)."""

    return [
        event
        for event in events
        if event.get("significance") in ("high", "medium")
        or len(event.get("article_ids", [])) >= MIN_ARTICLES_FOR_SIGNIFICANT_EVENT
    ]


def articles_needing_full_text(
    events: list[dict[str, Any]],
    article_map: dict[str, ArticleIndexEntry],
) -> list[ArticleIndexEntry]:
    """Collect unique articles from significant events for full-text loading."""

    seen: set[str] = set()
    result: list[ArticleIndexEntry] = []
    for event in events:
        for aid in event.get("article_ids", []):
            if aid not in seen and aid in article_map:
                seen.add(aid)
                result.append(article_map[aid])
    return result


def build_event_payloads(
    events: list[dict[str, Any]],
    enriched: dict[str, dict[str, str]],
    enriched_full: dict[str, dict[str, str]],
    article_map: dict[str, ArticleIndexEntry],
) -> list[dict[str, Any]]:
    """Merge enriched texts into event payloads for synthesis."""

    payloads: list[dict[str, Any]] = []
    for event in events:
        articles_data: list[dict[str, Any]] = []
        for aid in event.get("article_ids", []):
            entry = article_map.get(aid)
            if not entry:
                continue
            full = enriched_full.get(aid, {})
            partial = enriched.get(aid, {})
            text = full.get("clean_text") or partial.get("clean_text", "")
            title = full.get("new_title") or partial.get("new_title") or entry.title
            articles_data.append(
                {
                    "article_id": aid,
                    "title": title,
                    "url": entry.url,
                    "source": entry.source,
                    "text": text,
                },
            )
        payloads.append(
            {
                "event_id": event.get("event_id", ""),
                "title": event.get("title", ""),
                "significance": event.get("significance", "medium"),
                "articles": articles_data,
            },
        )
    return payloads


def events_to_resource_files(events: list[dict[str, Any]]) -> dict[str, bytes | str]:
    """Serialize events as individual JSON files for LLM input."""

    resources: dict[str, bytes | str] = {}
    for event in events:
        eid = event.get("event_id", str(uuid4())[:8])
        resources[f"event_{eid}.json"] = json.dumps(event, ensure_ascii=False, indent=2)
    return resources


def build_routing_defaults(settings: Settings) -> RoutingDefaults:
    """Build RoutingDefaults from Settings for the recap pipeline."""

    return RoutingDefaults(
        default_agent=settings.orchestrator.default_agent,
        task_type_profile_map=settings.orchestrator.task_type_profile_map,
        command_templates={
            "claude": settings.orchestrator.claude_command_template,
            "codex": settings.orchestrator.codex_command_template,
            "gemini": settings.orchestrator.gemini_command_template,
        },
        models={
            "claude": {
                "fast": settings.orchestrator.claude_model_fast,
                "quality": settings.orchestrator.claude_model_quality,
            },
            "codex": {
                "fast": settings.orchestrator.codex_model_fast,
                "quality": settings.orchestrator.codex_model_quality,
            },
            "gemini": {
                "fast": settings.orchestrator.gemini_model_fast,
                "quality": settings.orchestrator.gemini_model_quality,
            },
        },
    )
