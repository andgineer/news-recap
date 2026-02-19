"""Intelligence controllers: stories, continuity, highlights, monitors, and Q&A."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from news_recap.config import Settings
from news_recap.orchestrator.models import (
    DailyStorySnapshotWrite,
    MonitorQuestionWrite,
    OutputFeedbackWrite,
    ReadStateEventWrite,
    SourceCorpusEntry,
    StoryAssignmentView,
    StoryAssignmentWrite,
    StoryDefinitionView,
    StoryDefinitionWrite,
    UserOutputView,
)
from news_recap.orchestrator.repository import OrchestratorRepository
from news_recap.orchestrator.routing import RoutingDefaults
from news_recap.orchestrator.services import EnqueueDemoTask, OrchestratorService

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
    """High-level intelligence operations on top of ingestion + orchestrator."""

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
        routing_defaults = _routing_defaults(settings=settings)
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

            service = OrchestratorService(
                repository=repository,
                workdir_root=settings.orchestrator.workdir_root,
                routing_defaults=routing_defaults,
            )
            task = service.enqueue_demo_task(
                EnqueueDemoTask(
                    task_type="highlights",
                    prompt=_highlights_prompt(business_date=business_date),
                    source_ids=(),
                    article_entries=filtered_entries,
                    priority=command.priority,
                    max_attempts=command.max_attempts,
                    timeout_seconds=command.timeout_seconds,
                    agent=command.agent,
                    model_profile=command.model_profile,
                    model=command.model,
                    story_context={
                        "business_date": business_date.isoformat(),
                        "stories": [
                            {
                                "story_key": snapshot.story_key,
                                "title": snapshot.title,
                                "continuity_key": snapshot.continuity_key,
                                "summary": snapshot.summary,
                            }
                            for snapshot in snapshots
                        ],
                        "seen_source_ids": sorted(seen_source_ids),
                    },
                    continuity_summary={
                        "business_date": business_date.isoformat(),
                        "yesterday": [
                            {
                                "story_key": snapshot.story_key,
                                "title": snapshot.title,
                                "continuity_key": snapshot.continuity_key,
                                "summary": snapshot.summary,
                            }
                            for snapshot in prior_snapshots
                        ],
                    },
                    output_target={
                        "kind": "highlights",
                        "business_date": business_date.isoformat(),
                        "status": "ready",
                        "title": f"Highlights for {business_date.isoformat()}",
                    },
                ),
            )

        return [
            "Highlights task enqueued: "
            f"task_id={task.task_id} date={business_date.isoformat()} "
            f"sources={len(filtered_entries)}",
        ]

    def generate_story_details(self, command: StoryDetailsGenerateCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = _routing_defaults(settings=settings)
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
                summary = {}
            else:
                title = snapshot.title
                story_key = snapshot.story_key
                summary = snapshot.summary
            prior_snapshots = repository.get_latest_daily_story_snapshots_before(
                business_date=business_date,
            )

            service = OrchestratorService(
                repository=repository,
                workdir_root=settings.orchestrator.workdir_root,
                routing_defaults=routing_defaults,
            )
            task = service.enqueue_demo_task(
                EnqueueDemoTask(
                    task_type="story_details",
                    prompt=(
                        f"Produce detailed update for story {title!r} on "
                        f"{business_date.isoformat()}."
                    ),
                    source_ids=(),
                    article_entries=entries,
                    priority=command.priority,
                    max_attempts=command.max_attempts,
                    timeout_seconds=command.timeout_seconds,
                    agent=command.agent,
                    model_profile=command.model_profile,
                    model=command.model,
                    story_context={
                        "business_date": business_date.isoformat(),
                        "story": {
                            "story_id": command.story_id,
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
                    output_target={
                        "kind": "story_details",
                        "business_date": business_date.isoformat(),
                        "story_id": command.story_id,
                        "status": "ready",
                        "title": title,
                    },
                ),
            )

        return [
            "Story details task enqueued: "
            f"task_id={task.task_id} story_id={command.story_id} "
            f"date={business_date.isoformat()} sources={len(entries)}",
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
        routing_defaults = _routing_defaults(settings=settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        lines: list[str] = []

        with _repository(settings) as repository:
            monitors = repository.list_monitor_questions(include_disabled=False)
            if not monitors:
                return ["No enabled monitors configured."]

            service = OrchestratorService(
                repository=repository,
                workdir_root=settings.orchestrator.workdir_root,
                routing_defaults=routing_defaults,
            )
            for monitor in monitors:
                retrieval_entries, retrieval_context = _build_retrieval_context(
                    repository=repository,
                    settings=settings,
                    business_date=business_date,
                    lookback_days=settings.orchestrator.qa_lookback_days,
                )
                task = service.enqueue_demo_task(
                    EnqueueDemoTask(
                        task_type="monitor_answer",
                        prompt=monitor.prompt,
                        source_ids=(),
                        article_entries=retrieval_entries,
                        priority=command.priority,
                        max_attempts=command.max_attempts,
                        timeout_seconds=command.timeout_seconds,
                        agent=command.agent,
                        model_profile=command.model_profile,
                        model=command.model,
                        retrieval_context=retrieval_context,
                        output_target={
                            "kind": "monitor_answer",
                            "business_date": business_date.isoformat(),
                            "monitor_id": monitor.monitor_id,
                            "status": "ready",
                            "title": monitor.name,
                        },
                    ),
                )
                lines.append(
                    "Monitor task enqueued: "
                    f"monitor_id={monitor.monitor_id} task_id={task.task_id} "
                    f"sources={len(retrieval_entries)}",
                )

        return lines

    def ask_qa(self, command: QaAskCommand) -> list[str]:
        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = _routing_defaults(settings=settings)
        business_date = datetime.now(tz=UTC).date()
        lookback_days = command.lookback_days or settings.orchestrator.qa_lookback_days

        with _repository(settings) as repository:
            retrieval_entries, retrieval_context = _build_retrieval_context(
                repository=repository,
                settings=settings,
                business_date=business_date,
                lookback_days=lookback_days,
            )
            service = OrchestratorService(
                repository=repository,
                workdir_root=settings.orchestrator.workdir_root,
                routing_defaults=routing_defaults,
            )
            request_id = str(uuid4())
            task = service.enqueue_demo_task(
                EnqueueDemoTask(
                    task_type="qa",
                    prompt=command.prompt,
                    source_ids=(),
                    article_entries=retrieval_entries,
                    priority=command.priority,
                    max_attempts=command.max_attempts,
                    timeout_seconds=command.timeout_seconds,
                    agent=command.agent,
                    model_profile=command.model_profile,
                    model=command.model,
                    retrieval_context=retrieval_context,
                    output_target={
                        "kind": "qa_answer",
                        "business_date": business_date.isoformat(),
                        "request_id": request_id,
                        "status": "ready",
                        "title": "Ad-hoc answer",
                    },
                ),
            )

        return [
            "Q&A task enqueued: "
            f"task_id={task.task_id} request_id={request_id} "
            f"lookback_days={lookback_days} sources={len(retrieval_entries)}",
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


def _resolve_assignment_entries(
    *,
    repository: OrchestratorRepository,
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
    repository: OrchestratorRepository,
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


def _highlights_prompt(*, business_date: date) -> str:
    return (
        "Generate 5-10 concise highlights for the day with strict source mapping. "
        f"Business date: {business_date.isoformat()}. "
        "Avoid repeating points the user has already seen in prior outputs when possible."
    )


def _keyword_tokens(text: str) -> set[str]:
    parts = [token.strip(".,:;!?()[]{}\"'`“”«»").lower() for token in text.split()]
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
def _repository(settings: Settings) -> Iterator[OrchestratorRepository]:
    repository = OrchestratorRepository(
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
