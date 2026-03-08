"""Prepare inputs and launch the recap pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import msgspec

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.agents.routing import RoutingDefaults
from news_recap.recap.flow import recap_flow
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import _DEFAULT_MIN_RESOURCE_CHARS
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)

_DIGEST_FILENAME = "digest.json"


def _build_routing_defaults(settings: Settings) -> RoutingDefaults:
    """Build RoutingDefaults from Settings for the recap pipeline."""
    return RoutingDefaults(
        default_agent=settings.orchestrator.default_agent,
        task_model_map=settings.orchestrator.task_model_map,
        command_templates={
            "claude": settings.orchestrator.claude_command_template,
            "codex": settings.orchestrator.codex_command_template,
            "gemini": settings.orchestrator.gemini_command_template,
        },
        task_type_timeout_map=settings.orchestrator.task_type_timeout_map,
        agent_max_parallel=settings.orchestrator.agent_max_parallel,
        agent_launch_delay=settings.orchestrator.agent_launch_delay,
        execution_backend=settings.orchestrator.execution_backend,
        api_model_map=settings.orchestrator.api_model_map,
        api_max_parallel=settings.orchestrator.api_max_parallel,
        api_concurrency_recovery_successes=settings.orchestrator.api_concurrency_recovery_successes,
        api_downshift_pause_seconds=settings.orchestrator.api_downshift_pause_seconds,
        api_retry_max_backoff_seconds=settings.orchestrator.api_retry_max_backoff_seconds,
        api_retry_jitter_seconds=settings.orchestrator.api_retry_jitter_seconds,
    )


@dataclass(slots=True)
class RecapRunCommand:
    """CLI parameters for a pipeline launch."""

    data_dir: Path | None = None
    business_date: date | None = None
    agent_override: str | None = None
    article_limit: int | None = None
    stop_after: str | None = None
    fresh: bool = False
    api_mode: bool = False


def _find_resumable_pipeline(
    workdir_root: Path,
    business_date: date,
    article_limit: int | None,
) -> Path | None:
    """Find the latest incomplete pipeline dir for *business_date*.

    Returns ``None`` when no resumable candidate exists or the candidate
    was created with a different article limit (comparing actual article
    count to the requested limit).
    """
    if not workdir_root.is_dir():
        return None

    prefix = f"pipeline-{business_date}-"
    candidates: list[Path] = sorted(
        (p for p in workdir_root.iterdir() if p.is_dir() and p.name.startswith(prefix)),
        key=lambda p: p.name,
        reverse=True,
    )

    for pdir in candidates:
        digest_path = pdir / _DIGEST_FILENAME
        if not digest_path.exists():
            continue
        try:
            digest = load_msgspec(digest_path, Digest)
        except Exception:  # noqa: BLE001
            logger.debug("Cannot read digest in %s, skipping", pdir.name)
            continue

        if article_limit and len(digest.articles) != article_limit:
            logger.info(
                "Skipping %s: article count mismatch (%d vs requested %d)",
                pdir.name,
                len(digest.articles),
                article_limit,
            )
            continue

        return pdir

    return None


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    business_date: date,
    articles: list[DigestArticle],
    preferences: UserPreferences,
    routing_defaults: RoutingDefaults,
    agent_override: str | None,
    data_dir: str,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
    dedup_threshold: float = 0.90,
    dedup_model_name: str = "intfloat/multilingual-e5-small",
) -> None:
    """Serialize all pipeline inputs to ``pipeline_input.json`` in *pipeline_dir*."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "business_date": business_date.isoformat(),
        "articles": [msgspec.structs.asdict(a) for a in articles],
        "preferences": msgspec.structs.asdict(preferences),
        "routing_defaults": msgspec.structs.asdict(routing_defaults),
        "agent_override": agent_override,
        "data_dir": data_dir,
        "min_resource_chars": min_resource_chars,
        "dedup_threshold": dedup_threshold,
        "dedup_model_name": dedup_model_name,
    }
    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        "utf-8",
    )


def _patch_agent_override(pipeline_dir: Path, agent: str) -> str | None:
    """Patch ``agent_override`` in an existing ``pipeline_input.json``.

    Returns the previous value (or ``None`` if unset).
    """
    path = pipeline_dir / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    old = raw.get("agent_override")
    raw["agent_override"] = agent.strip().lower()
    path.write_text(json.dumps(raw, ensure_ascii=False, default=str), "utf-8")
    return old


class RecapCliController:
    """Load articles, materialize pipeline inputs, and launch the recap flow."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Fetch articles from store, write pipeline_input.json, and run recap_flow."""

        settings = Settings.from_env(
            data_dir=command.data_dir,
            execution_backend="api" if command.api_mode else None,
        )
        routing_defaults = _build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        preferences = UserPreferences()

        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()

        resumable = None
        if not command.fresh:
            resumable = _find_resumable_pipeline(
                settings.orchestrator.workdir_root.resolve(),
                business_date,
                command.article_limit,
            )

        if resumable:
            pipeline_dir = resumable
            digest = load_msgspec(resumable / _DIGEST_FILENAME, Digest)
            yield (
                f"Resuming pipeline: {pipeline_dir.name} "
                f"({len(digest.completed_phases)} phase(s) done: "
                f"{', '.join(digest.completed_phases) or 'none'})"
            )
            if command.agent_override:
                new_agent = command.agent_override.strip().lower()
                old_agent = _patch_agent_override(pipeline_dir, new_agent)
                yield f"Agent override changed: {old_agent or 'default'} -> {new_agent}"
        else:
            fetch_limit = command.article_limit or 2000
            articles = store.list_retrieval_articles(
                lookback_days=settings.ingestion.digest_lookback_days,
                limit=fetch_limit,
            )
            if not articles:
                yield "No articles found. Run ingestion first."
                return

            limit_note = f" (limited to {fetch_limit})" if command.article_limit else ""
            yield f"Found {len(articles)} articles for {business_date}{limit_note}"

            ts = datetime.now(tz=UTC).strftime("%H%M%S")
            pipeline_dir = (
                settings.orchestrator.workdir_root / f"pipeline-{business_date}-{ts}"
            ).resolve()
            _write_pipeline_input(
                pipeline_dir,
                business_date=business_date,
                articles=articles,
                preferences=preferences,
                routing_defaults=routing_defaults,
                agent_override=command.agent_override,
                data_dir=str(settings.data_dir),
                min_resource_chars=settings.ingestion.min_resource_chars,
                dedup_threshold=settings.dedup.threshold,
                dedup_model_name=settings.dedup.model_name,
            )
            yield f"New pipeline: {pipeline_dir}"

        yield "Starting pipeline…"

        recap_flow(
            pipeline_dir=str(pipeline_dir),
            business_date=business_date.isoformat(),
            stop_after=command.stop_after,
        )
