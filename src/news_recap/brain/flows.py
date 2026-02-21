"""Intelligence flows: stories, highlights, monitors, and Q&A.

Each LLM operation runs synchronously via Prefect ``@flow`` / ``@task``,
calling CLI agents directly through ``agent_runtime.run_agent_task``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from prefect import flow

from news_recap.agent_runtime import AgentTaskResult, run_agent_task
from news_recap.brain.contracts import ArticleIndexEntry
from news_recap.brain.models import (
    DailyStorySnapshotWrite,
    MonitorQuestionWrite,
    OutputFeedbackWrite,
    ReadStateEventWrite,
    SourceCorpusEntry,
    StoryAssignmentView,
    StoryAssignmentWrite,
    StoryDefinitionView,
    StoryDefinitionWrite,
    UserOutputBlockWrite,
    UserOutputUpsert,
    UserOutputView,
)
from news_recap.brain.pricing import estimate_cost_usd
from news_recap.brain.routing import RoutingDefaults
from news_recap.brain.sanitization import sanitize_preview
from news_recap.brain.usage import extract_usage
from news_recap.brain.workdir import TaskWorkdirManager
from news_recap.config import Settings
from news_recap.ingestion.repository import SQLiteRepository

logger = logging.getLogger(__name__)

MIN_KEYWORD_TOKEN_LENGTH = 4


@dataclass(slots=True)
class StoryDefineCommand:
    db_path: Path | None
    story_id: str | None
    name: str
    description: str
    target_language: str
    priority: int
    enabled: bool


@dataclass(slots=True)
class StoryListCommand:
    db_path: Path | None
    include_disabled: bool


@dataclass(slots=True)
class StoryBuildCommand:
    db_path: Path | None
    business_date: date | None


@dataclass(slots=True)
class HighlightsGenerateCommand:
    db_path: Path | None
    business_date: date | None
    priority: int
    max_attempts: int
    timeout_seconds: int
    agent: str | None
    model_profile: str | None
    model: str | None


@dataclass(slots=True)
class StoryDetailsGenerateCommand:
    db_path: Path | None
    business_date: date | None
    story_id: str
    priority: int
    max_attempts: int
    timeout_seconds: int
    agent: str | None
    model_profile: str | None
    model: str | None


@dataclass(slots=True)
class MonitorUpsertCommand:
    db_path: Path | None
    monitor_id: str | None
    name: str
    prompt: str
    cadence: str
    enabled: bool


@dataclass(slots=True)
class MonitorListCommand:
    db_path: Path | None
    include_disabled: bool


@dataclass(slots=True)
class MonitorRunCommand:
    db_path: Path | None
    business_date: date | None
    priority: int
    max_attempts: int
    timeout_seconds: int
    agent: str | None
    model_profile: str | None
    model: str | None


@dataclass(slots=True)
class QaAskCommand:
    db_path: Path | None
    prompt: str
    lookback_days: int | None
    priority: int
    max_attempts: int
    timeout_seconds: int
    agent: str | None
    model_profile: str | None
    model: str | None


@dataclass(slots=True)
class ReadStateMarkCommand:
    db_path: Path | None
    output_id: str
    event_type: str
    output_block_id: int | None


@dataclass(slots=True)
class FeedbackAddCommand:
    db_path: Path | None
    output_id: str
    feedback_type: str
    value: str | None
    output_block_id: int | None


@dataclass(slots=True)
class IntelligenceStatsCommand:
    db_path: Path | None
    hours: int


class IntelligenceCliController:
    """High-level intelligence operations using Prefect flows."""

    def define_story(self, command: StoryDefineCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            story = repository.upsert_story_definition(
                StoryDefinitionWrite(
                    story_id=command.story_id,
                    name=command.name,
                    description=command.description,
                    target_language=command.target_language,
                    priority=command.priority,
                    enabled=command.enabled,
                ),
            )
        return [
            "Story saved: "
            f"story_id={story.story_id} name={story.name!r} lang={story.target_language} "
            f"priority={story.priority} enabled={story.enabled}",
        ]

    def list_stories(self, command: StoryListCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            stories = repository.list_story_definitions(include_disabled=command.include_disabled)

        lines = [f"Stories: {len(stories)}"]
        for story in stories:
            lines.append(
                f"  {story.story_id} priority={story.priority} enabled={story.enabled} "
                f"lang={story.target_language} name={story.name}",
            )
        return lines

    def build_stories(self, command: StoryBuildCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        day_start = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
        day_end = day_start + timedelta(days=1)

        with _repository(settings) as repository:
            articles = repository.list_user_retrieval_articles(
                limit=10_000,
                since=day_start,
                until=day_end,
            )
            if not articles:
                repository.replace_story_assignments(business_date=business_date, assignments=[])
                repository.replace_daily_story_snapshots(business_date=business_date, snapshots=[])
                return [f"No articles found for {business_date.isoformat()}; stories cleared."]

            pinned_stories = repository.list_story_definitions()
            assignments, story_titles = _build_assignments(
                business_date=business_date,
                articles=articles,
                pinned_stories=pinned_stories,
            )
            repository.replace_story_assignments(
                business_date=business_date,
                assignments=assignments,
            )
            snapshots = _build_daily_snapshots(
                business_date=business_date,
                assignments=assignments,
                article_entries=articles,
                story_titles=story_titles,
            )
            repository.replace_daily_story_snapshots(
                business_date=business_date,
                snapshots=snapshots,
            )

        pinned_count = sum(
            1 for assignment in assignments if assignment.assignment_type == "pinned"
        )
        auto_count = len(assignments) - pinned_count
        return [
            "Story build completed: "
            f"date={business_date.isoformat()} articles={len(articles)} "
            f"assignments={len(assignments)} pinned={pinned_count} auto={auto_count} "
            f"snapshots={len(snapshots)}",
        ]

    def generate_highlights(self, command: HighlightsGenerateCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        business_date = command.business_date or datetime.now(tz=UTC).date()

        with _repository(settings) as repository:
            assignments = repository.list_story_assignments(business_date=business_date)
            if not assignments:
                return [
                    "No story assignments found for date="
                    f"{business_date.isoformat()}. Run `news-recap stories build` first.",
                ]

            entries = _resolve_assignment_entries(repository=repository, assignments=assignments)
            seen_source_ids = repository.list_recent_read_source_ids(days=3)
            filtered_entries = [
                entry for entry in entries if entry.source_id not in seen_source_ids
            ] or entries
            snapshots = repository.list_daily_story_snapshots(business_date=business_date)
            prior_snapshots = repository.get_latest_daily_story_snapshots_before(
                business_date=business_date,
            )

            article_index = _entries_to_article_index(filtered_entries)
            result = _run_highlights_flow(
                settings=settings,
                business_date=business_date,
                article_index=article_index,
                snapshots=snapshots,
                prior_snapshots=prior_snapshots,
                seen_source_ids=seen_source_ids,
                command=command,
            )

            _persist_output(
                repository=repository,
                task_result=result,
                kind="highlights",
                business_date=business_date,
                title=f"Highlights for {business_date.isoformat()}",
                article_entries=filtered_entries,
            )

        return [
            "Highlights completed: "
            f"task_id={result.task_id} date={business_date.isoformat()} "
            f"sources={len(filtered_entries)} elapsed={result.elapsed_seconds:.1f}s",
        ]

    def generate_story_details(self, command: StoryDetailsGenerateCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        business_date = command.business_date or datetime.now(tz=UTC).date()

        with _repository(settings) as repository:
            assignments = [
                assignment
                for assignment in repository.list_story_assignments(business_date=business_date)
                if assignment.story_id == command.story_id
                or assignment.story_key == f"pinned:{command.story_id}"
            ]
            if not assignments:
                return [
                    "No assignments for story_id="
                    f"{command.story_id!r} on date={business_date.isoformat()}.",
                ]
            entries = _resolve_assignment_entries(repository=repository, assignments=assignments)
            snapshots = repository.list_daily_story_snapshots(business_date=business_date)
            snapshot = next(
                (
                    item
                    for item in snapshots
                    if item.story_id == command.story_id
                    or item.story_key == f"pinned:{command.story_id}"
                ),
                None,
            )
            if snapshot is None:
                title = f"Story {command.story_id}"
                story_key = f"pinned:{command.story_id}"
                summary: dict[str, object] = {}
            else:
                title = snapshot.title
                story_key = snapshot.story_key
                summary = snapshot.summary
            prior_snapshots = repository.get_latest_daily_story_snapshots_before(
                business_date=business_date,
            )

            article_index = _entries_to_article_index(entries)
            result = _run_story_details_flow(
                settings=settings,
                business_date=business_date,
                article_index=article_index,
                story_id=command.story_id,
                story_key=story_key,
                title=title,
                summary=summary,
                prior_snapshots=prior_snapshots,
                command=command,
            )

            _persist_output(
                repository=repository,
                task_result=result,
                kind="story_details",
                business_date=business_date,
                title=title,
                article_entries=entries,
                extra_meta={"story_id": command.story_id},
            )

        return [
            "Story details completed: "
            f"task_id={result.task_id} story_id={command.story_id} "
            f"date={business_date.isoformat()} sources={len(entries)} "
            f"elapsed={result.elapsed_seconds:.1f}s",
        ]

    def upsert_monitor(self, command: MonitorUpsertCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            monitor = repository.upsert_monitor_question(
                MonitorQuestionWrite(
                    monitor_id=command.monitor_id,
                    name=command.name,
                    prompt=command.prompt,
                    cadence=command.cadence,
                    enabled=command.enabled,
                ),
            )
        return [
            "Monitor saved: "
            f"monitor_id={monitor.monitor_id} name={monitor.name!r} "
            f"cadence={monitor.cadence} enabled={monitor.enabled}",
        ]

    def list_monitors(self, command: MonitorListCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            monitors = repository.list_monitor_questions(include_disabled=command.include_disabled)
        lines = [f"Monitors: {len(monitors)}"]
        for monitor in monitors:
            lines.append(
                f"  {monitor.monitor_id} cadence={monitor.cadence} "
                f"enabled={monitor.enabled} name={monitor.name}",
            )
        return lines

    def run_monitors(self, command: MonitorRunCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        lines: list[str] = []

        with _repository(settings) as repository:
            monitors = repository.list_monitor_questions(include_disabled=False)
            if not monitors:
                return ["No enabled monitors configured."]

            for monitor in monitors:
                retrieval_entries, retrieval_context = _build_retrieval_context(
                    repository=repository,
                    settings=settings,
                    business_date=business_date,
                    lookback_days=settings.orchestrator.qa_lookback_days,
                )

                article_index = _entries_to_article_index(retrieval_entries)
                result = _run_monitor_flow(
                    settings=settings,
                    business_date=business_date,
                    monitor=monitor,
                    article_index=article_index,
                    retrieval_context=retrieval_context,
                    command=command,
                )

                _persist_output(
                    repository=repository,
                    task_result=result,
                    kind="monitor_answer",
                    business_date=business_date,
                    title=monitor.name,
                    article_entries=retrieval_entries,
                    extra_meta={"monitor_id": monitor.monitor_id},
                )
                lines.append(
                    "Monitor completed: "
                    f"monitor_id={monitor.monitor_id} task_id={result.task_id} "
                    f"sources={len(retrieval_entries)} "
                    f"elapsed={result.elapsed_seconds:.1f}s",
                )

        return lines

    def ask_qa(self, command: QaAskCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        business_date = datetime.now(tz=UTC).date()
        lookback_days = command.lookback_days or settings.orchestrator.qa_lookback_days

        with _repository(settings) as repository:
            retrieval_entries, retrieval_context = _build_retrieval_context(
                repository=repository,
                settings=settings,
                business_date=business_date,
                lookback_days=lookback_days,
            )

            article_index = _entries_to_article_index(retrieval_entries)
            result = _run_qa_flow(
                settings=settings,
                business_date=business_date,
                prompt=command.prompt,
                article_index=article_index,
                retrieval_context=retrieval_context,
                command=command,
            )

            _persist_output(
                repository=repository,
                task_result=result,
                kind="qa_answer",
                business_date=business_date,
                title="Ad-hoc answer",
                article_entries=retrieval_entries,
                request_id=result.task_id,
            )

        return [
            "Q&A completed: "
            f"task_id={result.task_id} "
            f"lookback_days={lookback_days} sources={len(retrieval_entries)} "
            f"elapsed={result.elapsed_seconds:.1f}s",
        ]

    def mark_read_state(self, command: ReadStateMarkCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            output = repository.get_user_output(output_id=command.output_id)
            if output is None:
                return [f"Output not found: {command.output_id}"]
            repository.add_read_state_event(
                ReadStateEventWrite(
                    output_id=command.output_id,
                    event_type=command.event_type,
                    output_block_id=command.output_block_id,
                ),
            )
        return [
            f"Read-state recorded: output_id={command.output_id} event_type={command.event_type}",
        ]

    def add_feedback(self, command: FeedbackAddCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        with _repository(settings) as repository:
            output = repository.get_user_output(output_id=command.output_id)
            if output is None:
                return [f"Output not found: {command.output_id}"]
            repository.add_output_feedback(
                OutputFeedbackWrite(
                    output_id=command.output_id,
                    output_block_id=command.output_block_id,
                    feedback_type=command.feedback_type,
                    value=command.value,
                ),
            )
        return [
            "Feedback recorded: "
            f"output_id={command.output_id} feedback_type={command.feedback_type}",
        ]

    def stats(self, command: IntelligenceStatsCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        since = datetime.now(tz=UTC) - timedelta(hours=max(1, command.hours))
        with _repository(settings) as repository:
            metrics = repository.intelligence_stats_snapshot(since=since)

        return [
            f"Insights stats (window={command.hours}h)",
            f"Stories: total={metrics['stories_total']} enabled={metrics['stories_enabled']}",
            f"Assignments: {metrics['story_assignments_window']}",
            f"Daily snapshots: {metrics['story_snapshots_window']}",
            (
                "Outputs: "
                f"all={metrics['outputs_window']} "
                f"highlights={metrics['outputs_highlights_window']} "
                f"story_details={metrics['outputs_story_details_window']} "
                f"monitor={metrics['outputs_monitor_window']} "
                f"qa={metrics['outputs_qa_window']}"
            ),
            (
                "Engagement: "
                f"read_state_events={metrics['read_state_events_window']} "
                f"feedback_events={metrics['feedback_events_window']}"
            ),
        ]

    def list_outputs(
        self,
        *,
        db_path: Path | None,
        kind: str | None = None,
        business_date: date | None = None,
        limit: int = 20,
    ) -> list[str]:
        settings = Settings.from_env(db_path=db_path)
        with _repository(settings) as repository:
            outputs = repository.list_user_outputs(
                kind=kind,
                business_date=business_date,
                limit=limit,
            )
        return _render_outputs(outputs)


# ---------------------------------------------------------------------------
# Prefect intelligence flows
# ---------------------------------------------------------------------------


@flow(name="highlights_flow")
def _run_highlights_flow(  # noqa: PLR0913
    *,
    settings: Settings,
    business_date: date,
    article_index: list[ArticleIndexEntry],
    snapshots: list,
    prior_snapshots: list,
    seen_source_ids: set[str],
    command: HighlightsGenerateCommand,
) -> AgentTaskResult:
    routing_defaults = _routing_defaults(settings=settings)
    workdir_mgr = TaskWorkdirManager(settings.orchestrator.workdir_root)

    return run_agent_task(
        task_type="highlights",
        prompt=_highlights_prompt(business_date=business_date),
        workdir_mgr=workdir_mgr,
        routing_defaults=routing_defaults,
        article_entries=article_index,
        agent_override=command.agent,
        profile_override=command.model_profile,
        model_override=command.model,
        metadata={
            "output_target": {
                "kind": "highlights",
                "business_date": business_date.isoformat(),
                "status": "ready",
                "title": f"Highlights for {business_date.isoformat()}",
            },
        },
        story_context={
            "business_date": business_date.isoformat(),
            "stories": [
                {
                    "story_key": s.story_key,
                    "title": s.title,
                    "continuity_key": s.continuity_key,
                    "summary": s.summary,
                }
                for s in snapshots
            ],
            "seen_source_ids": sorted(seen_source_ids),
        },
        continuity_summary={
            "business_date": business_date.isoformat(),
            "yesterday": [
                {
                    "story_key": s.story_key,
                    "title": s.title,
                    "continuity_key": s.continuity_key,
                    "summary": s.summary,
                }
                for s in prior_snapshots
            ],
        },
        timeout_seconds=command.timeout_seconds,
    )


@flow(name="story_details_flow")
def _run_story_details_flow(  # noqa: PLR0913
    *,
    settings: Settings,
    business_date: date,
    article_index: list[ArticleIndexEntry],
    story_id: str,
    story_key: str,
    title: str,
    summary: dict[str, object],
    prior_snapshots: list,
    command: StoryDetailsGenerateCommand,
) -> AgentTaskResult:
    routing_defaults = _routing_defaults(settings=settings)
    workdir_mgr = TaskWorkdirManager(settings.orchestrator.workdir_root)

    return run_agent_task(
        task_type="story_details",
        prompt=(f"Produce detailed update for story {title!r} on {business_date.isoformat()}."),
        workdir_mgr=workdir_mgr,
        routing_defaults=routing_defaults,
        article_entries=article_index,
        agent_override=command.agent,
        profile_override=command.model_profile,
        model_override=command.model,
        metadata={
            "output_target": {
                "kind": "story_details",
                "business_date": business_date.isoformat(),
                "story_id": story_id,
                "status": "ready",
                "title": title,
            },
        },
        story_context={
            "business_date": business_date.isoformat(),
            "story": {
                "story_id": story_id,
                "story_key": story_key,
                "title": title,
                "summary": summary,
            },
        },
        continuity_summary={
            "business_date": business_date.isoformat(),
            "yesterday": [
                {
                    "story_key": item.story_key,
                    "title": item.title,
                    "continuity_key": item.continuity_key,
                    "summary": item.summary,
                }
                for item in prior_snapshots
            ],
        },
        timeout_seconds=command.timeout_seconds,
    )


@flow(name="monitor_flow")
def _run_monitor_flow(  # noqa: PLR0913
    *,
    settings: Settings,
    business_date: date,
    monitor: object,
    article_index: list[ArticleIndexEntry],
    retrieval_context: dict[str, object],
    command: MonitorRunCommand,
) -> AgentTaskResult:
    routing_defaults = _routing_defaults(settings=settings)
    workdir_mgr = TaskWorkdirManager(settings.orchestrator.workdir_root)

    return run_agent_task(
        task_type="monitor_answer",
        prompt=monitor.prompt,  # type: ignore[attr-defined]
        workdir_mgr=workdir_mgr,
        routing_defaults=routing_defaults,
        article_entries=article_index,
        agent_override=command.agent,
        profile_override=command.model_profile,
        model_override=command.model,
        retrieval_context=retrieval_context,
        metadata={
            "output_target": {
                "kind": "monitor_answer",
                "business_date": business_date.isoformat(),
                "monitor_id": monitor.monitor_id,  # type: ignore[attr-defined]
                "status": "ready",
                "title": monitor.name,  # type: ignore[attr-defined]
            },
        },
        timeout_seconds=command.timeout_seconds,
    )


@flow(name="qa_flow")
def _run_qa_flow(  # noqa: PLR0913
    *,
    settings: Settings,
    business_date: date,
    prompt: str,
    article_index: list[ArticleIndexEntry],
    retrieval_context: dict[str, object],
    command: QaAskCommand,
) -> AgentTaskResult:
    routing_defaults = _routing_defaults(settings=settings)
    workdir_mgr = TaskWorkdirManager(settings.orchestrator.workdir_root)

    return run_agent_task(
        task_type="qa",
        prompt=prompt,
        workdir_mgr=workdir_mgr,
        routing_defaults=routing_defaults,
        article_entries=article_index,
        agent_override=command.agent,
        profile_override=command.model_profile,
        model_override=command.model,
        retrieval_context=retrieval_context,
        metadata={
            "output_target": {
                "kind": "qa_answer",
                "business_date": business_date.isoformat(),
                "status": "ready",
                "title": "Ad-hoc answer",
            },
        },
        timeout_seconds=command.timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Output persistence
# ---------------------------------------------------------------------------


def _persist_output(  # noqa: PLR0913
    *,
    repository: SQLiteRepository,
    task_result: AgentTaskResult,
    kind: str,
    business_date: date,
    title: str,
    article_entries: list[SourceCorpusEntry],
    extra_meta: dict[str, object] | None = None,
    request_id: str | None = None,
) -> None:
    """Persist agent output to user_outputs with inlined citations."""
    citations = [
        {
            "source_id": entry.source_id,
            "title": entry.title,
            "url": entry.url,
            "source": entry.source,
            "published_at": entry.published_at.isoformat(),
        }
        for entry in article_entries
    ]

    payload: dict[str, object] = {
        **task_result.output,
        "citations": citations,
    }
    if extra_meta:
        payload.update(extra_meta)

    _log_usage_artifact(task_result)

    blocks = _extract_output_blocks(task_result.output)
    repository.upsert_user_output(
        UserOutputUpsert(
            kind=kind,
            business_date=business_date,
            status="ready",
            title=title,
            payload=payload,
            blocks=blocks,
            request_id=request_id,
        ),
    )


def _extract_output_blocks(output: dict[str, object]) -> list[UserOutputBlockWrite]:
    """Extract structured blocks from agent output if present."""
    raw_blocks = output.get("blocks")
    if not isinstance(raw_blocks, list):
        return []
    result: list[UserOutputBlockWrite] = []
    for i, block in enumerate(raw_blocks):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text", ""))
        source_ids = tuple(str(sid) for sid in block.get("source_ids", ()))
        result.append(UserOutputBlockWrite(block_order=i + 1, text=text, source_ids=source_ids))
    return result


def _log_usage_artifact(result: AgentTaskResult) -> None:
    """Log usage and cost as Prefect artifact (best-effort)."""
    try:
        usage = extract_usage(agent=result.agent, stdout="", stderr="")
        cost = estimate_cost_usd(
            agent=result.agent,
            model=result.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )
        logger.info(
            "Usage: agent=%s model=%s tokens=%s cost=%s",
            sanitize_preview(result.agent),
            sanitize_preview(result.model),
            usage.total_tokens,
            f"${cost:.6f}" if cost is not None else "n/a",
        )
    except Exception:  # noqa: BLE001
        logger.debug("Usage extraction failed", exc_info=True)


# ---------------------------------------------------------------------------
# Story assignment helpers (unchanged business logic)
# ---------------------------------------------------------------------------


def _build_assignments(
    *,
    business_date: date,
    articles: list[SourceCorpusEntry],
    pinned_stories: list[StoryDefinitionView],
) -> tuple[list[StoryAssignmentWrite], dict[str, str]]:
    story_titles: dict[str, str] = {}
    assignments: list[StoryAssignmentWrite] = []

    pinned_index = []
    for story in pinned_stories:
        tokens = _keyword_tokens(f"{story.name} {story.description}")
        pinned_index.append((story, tokens))

    for article in articles:
        article_tokens = _keyword_tokens(article.title)
        best_story = None
        best_score = 0.0
        for story, tokens in pinned_index:
            if not tokens:
                continue
            overlap = article_tokens.intersection(tokens)
            if not overlap:
                continue
            score = len(overlap) / len(tokens)
            if score > best_score:
                best_score = score
                best_story = story
        if best_story is not None:
            story_key = f"pinned:{best_story.story_id}"
            story_titles.setdefault(story_key, best_story.name)
            assignments.append(
                StoryAssignmentWrite(
                    business_date=business_date,
                    article_id=article.article_id,
                    story_id=best_story.story_id,
                    story_key=story_key,
                    assignment_type="pinned",
                    score=best_score,
                ),
            )
            continue

        auto_token = _auto_story_token(article.title)
        auto_source = article.source or "unknown"
        story_key = f"auto:{auto_source}:{auto_token}"
        story_titles.setdefault(story_key, f"Auto: {auto_source} / {auto_token}")
        assignments.append(
            StoryAssignmentWrite(
                business_date=business_date,
                article_id=article.article_id,
                story_id=None,
                story_key=story_key,
                assignment_type="auto",
                score=0.0,
            ),
        )

    assignments.sort(
        key=lambda item: (
            item.assignment_type != "pinned",
            item.story_key,
            -item.score,
            item.article_id,
        ),
    )
    return assignments, story_titles


def _build_daily_snapshots(
    *,
    business_date: date,
    assignments: list[StoryAssignmentWrite],
    article_entries: list[SourceCorpusEntry],
    story_titles: dict[str, str],
) -> list[DailyStorySnapshotWrite]:
    entry_by_article_id = {entry.article_id: entry for entry in article_entries}
    grouped: dict[str, list[StoryAssignmentWrite]] = defaultdict(list)
    for assignment in assignments:
        grouped[assignment.story_key].append(assignment)

    snapshots: list[DailyStorySnapshotWrite] = []
    for story_key in sorted(grouped):
        grouped_assignments = grouped[story_key]
        titles: list[str] = []
        sources: list[str] = []
        for assignment in grouped_assignments[:5]:
            entry = entry_by_article_id.get(assignment.article_id)
            if entry is None:
                continue
            titles.append(entry.title)
            sources.append(entry.source)

        snapshots.append(
            DailyStorySnapshotWrite(
                business_date=business_date,
                story_id=grouped_assignments[0].story_id,
                story_key=story_key,
                title=story_titles.get(story_key, story_key),
                continuity_key=story_key,
                summary={
                    "article_count": len(grouped_assignments),
                    "sample_titles": titles,
                    "sample_sources": sources,
                },
            ),
        )
    return snapshots


# ---------------------------------------------------------------------------
# Source resolution / retrieval helpers
# ---------------------------------------------------------------------------


def _resolve_assignment_entries(
    *,
    repository: SQLiteRepository,
    assignments: list[StoryAssignmentView],
) -> list[SourceCorpusEntry]:
    source_ids = tuple(f"article:{assignment.article_id}" for assignment in assignments)
    resolved, missing = repository.validate_user_source_ids(source_ids=source_ids)
    if missing:
        raise ValueError(
            "Missing user-scope source ids for assignments: " + ", ".join(sorted(missing)),
        )
    return resolved


def _build_retrieval_context(
    *,
    repository: SQLiteRepository,
    settings: Settings,
    business_date: date,
    lookback_days: int,
) -> tuple[list[SourceCorpusEntry], dict[str, object]]:
    lookback_days = max(1, lookback_days)
    window_end = datetime.combine(
        business_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    window_start = window_end - timedelta(days=lookback_days)

    candidates = repository.list_user_retrieval_articles(
        limit=max(
            settings.orchestrator.retrieval_max_articles * 5,
            settings.orchestrator.retrieval_top_k,
        ),
        since=window_start,
        until=window_end,
    )
    ranked = sorted(
        candidates,
        key=lambda entry: (
            -entry.published_at.timestamp(),
            entry.source_id,
        ),
    )

    top_k = max(1, settings.orchestrator.retrieval_top_k)
    max_articles = max(1, settings.orchestrator.retrieval_max_articles)
    bounded = ranked[:top_k]
    bounded = bounded[:max_articles]

    items: list[dict[str, object]] = []
    for index, entry in enumerate(bounded):
        score = max(0.0, 1.0 - (index * 0.001))
        items.append(
            {
                "rank": index + 1,
                "source_id": entry.source_id,
                "score": round(score, 6),
                "published_at": entry.published_at.isoformat(),
                "title": entry.title,
                "url": entry.url,
                "source": entry.source,
            },
        )

    retrieval_context: dict[str, object] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "lookback_days": lookback_days,
        "top_k": top_k,
        "max_articles": max_articles,
        "token_budget": settings.orchestrator.retrieval_token_budget,
        "char_budget": settings.orchestrator.retrieval_char_budget,
        "ranking_policy": "published_at_desc_source_id_asc",
        "items": items,
    }
    return bounded, retrieval_context


def _entries_to_article_index(entries: list[SourceCorpusEntry]) -> list[ArticleIndexEntry]:
    return [
        ArticleIndexEntry(
            source_id=entry.source_id,
            title=entry.title,
            url=entry.url,
            source=entry.source,
            published_at=entry.published_at.isoformat(),
        )
        for entry in entries
    ]


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _highlights_prompt(*, business_date: date) -> str:
    return (
        "Generate 5-10 concise highlights for the day with strict source mapping. "
        f"Business date: {business_date.isoformat()}. "
        "Avoid repeating points the user has already seen in prior outputs when possible."
    )


def _keyword_tokens(text: str) -> set[str]:
    parts = [
        token.strip(".,:;!?()[]{}\"'`\u201c\u201d\u00ab\u00bb").lower() for token in text.split()
    ]
    return {token for token in parts if len(token) >= MIN_KEYWORD_TOKEN_LENGTH}


def _auto_story_token(title: str) -> str:
    for token in sorted(_keyword_tokens(title), key=len, reverse=True):
        return token
    return "misc"


def _render_outputs(outputs: list[UserOutputView]) -> list[str]:
    lines = [f"Outputs: {len(outputs)}"]
    for output in outputs:
        lines.append(
            f"  {output.output_id} kind={output.kind} status={output.status} "
            f"date={output.business_date.isoformat()} blocks={len(output.blocks)}",
        )
    return lines


@contextmanager
def _repository(settings: Settings) -> Iterator[SQLiteRepository]:
    repository = SQLiteRepository(
        settings.db_path,
        user_id=settings.user_context.user_id,
        user_name=settings.user_context.user_name,
    )
    repository.init_schema()
    try:
        yield repository
    finally:
        repository.close()


def _routing_defaults(*, settings: Settings) -> RoutingDefaults:
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
