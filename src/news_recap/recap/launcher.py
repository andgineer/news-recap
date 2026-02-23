"""Prepare inputs and launch the DB-centric recap Prefect pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from news_recap.config import Settings, configure_prefect_runtime, resolve_prefect_mode
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.recap.flow import recap_flow
from news_recap.recap.runner import (
    UserPreferences,
    build_routing_defaults,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecapRunCommand:
    """CLI parameters for a pipeline launch."""

    db_path: Path | None = None
    business_date: date | None = None
    agent_override: str | None = None
    article_limit: int | None = None
    classify_only: bool = False
    debug_step: str | None = None
    stop_after: str | None = None


@dataclass(slots=True)
class RecapTrashCommand:
    """CLI parameters for trashing a digest."""

    db_path: Path | None = None
    digest_id: str | None = None
    drop_enrichment: bool = False
    force: bool = False


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    business_date: date,
    articles: list,
    preferences: UserPreferences,
    routing_defaults: object,
    agent_override: str | None,
) -> None:
    """Serialize pipeline routing info to ``pipeline_input.json``."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "business_date": business_date.isoformat(),
        "articles": [a.to_dict() for a in articles],
        "preferences": preferences.to_dict(),
        "routing_defaults": routing_defaults.to_dict(),  # type: ignore[union-attr]
        "agent_override": agent_override,
    }
    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        "utf-8",
    )


class RecapCliController:
    """Load articles, materialize pipeline inputs, and launch the Prefect flow."""

    def run_pipeline(self, command: RecapRunCommand) -> Iterator[str]:
        """Create/resume digest, assign articles, write pipeline_input.json, run flow."""

        settings = Settings.from_env(db_path=command.db_path)
        routing_defaults = build_routing_defaults(settings)
        business_date = command.business_date or datetime.now(tz=UTC).date()
        preferences = UserPreferences()

        mode = resolve_prefect_mode()
        effective_mode = configure_prefect_runtime(mode)
        yield f"Prefect runtime: {effective_mode.value}"

        with _repository(settings) as repository:
            digest_id, created = repository.create_or_resume_digest(
                business_date=business_date,
                pipeline_dir="",
            )
            verb = "Created" if created else "Resumed"
            yield f"{verb} digest {digest_id} for {business_date}"

            assigned = repository.assign_articles_to_digest(
                digest_id=digest_id,
                limit=command.article_limit,
            )
            if assigned > 0:
                limit_note = (
                    f" (limited to {command.article_limit})" if command.article_limit else ""
                )
                yield f"Assigned {assigned} articles{limit_note}"

            articles = repository.get_unclassified_articles(digest_id)
            kept = repository.get_kept_articles(digest_id)
            total = len(articles) + len(kept)
            if total == 0:
                yield "No articles in digest. Run ingestion first."
                return

            digest = repository.get_digest(digest_id)
            if digest is not None and digest.pipeline_dir:
                pipeline_dir = Path(digest.pipeline_dir)
            else:
                ts = datetime.now(tz=UTC).strftime("%H%M%S")
                pipeline_dir = (
                    settings.orchestrator.workdir_root / f"pipeline-{business_date}-{ts}"
                ).resolve()

            all_articles = repository.list_user_retrieval_articles(
                limit=command.article_limit or 2000,
            )
            _write_pipeline_input(
                pipeline_dir,
                business_date=business_date,
                articles=all_articles,
                preferences=preferences,
                routing_defaults=routing_defaults,
                agent_override=command.agent_override,
            )

            if created or (digest is not None and not digest.pipeline_dir):
                from sqlmodel import Session

                from news_recap.storage.sqlmodel_models import RecapDigest

                with Session(repository.engine) as session:
                    d = session.get(RecapDigest, digest_id)
                    if d is not None:
                        d.pipeline_dir = str(pipeline_dir)
                        session.add(d)
                        session.commit()

            yield f"Pipeline dir: {pipeline_dir}"
            yield f"Digest: {digest_id} ({total} articles)"
            if command.debug_step:
                yield f"Debug step: {command.debug_step}"
            if command.stop_after:
                yield f"Stop after: {command.stop_after}"
            yield "Starting pipeline…"

            recap_flow(
                pipeline_dir=str(pipeline_dir),
                business_date=business_date.isoformat(),
                db_path=str(settings.db_path),
                digest_id=digest_id,
                user_id=settings.user_context.user_id,
                debug_step=command.debug_step,
                stop_after=command.stop_after,
                classify_only=command.classify_only,
            )

    def trash_digest(self, command: RecapTrashCommand) -> Iterator[str]:
        """Delete a digest and release its articles."""
        settings = Settings.from_env(db_path=command.db_path)

        with _repository(settings) as repository:
            digest_id = command.digest_id
            if digest_id is None:
                today = datetime.now(tz=UTC).date()
                digest_id_found, _ = repository.create_or_resume_digest(
                    business_date=today,
                    pipeline_dir="",
                )
                digest = repository.get_digest(digest_id_found)
                if digest is None:
                    yield f"No draft digest to trash for {today}."
                    return
                digest_id = digest_id_found

            try:
                trashed = repository.trash_digest(
                    digest_id,
                    drop_enrichment=command.drop_enrichment,
                    force=command.force,
                )
            except ValueError as e:
                yield str(e)
                return

            if trashed:
                drop_note = " (enrichment dropped)" if command.drop_enrichment else ""
                yield f"Trashed digest {digest_id}{drop_note}"
            else:
                yield f"Digest {digest_id} not found."


@contextmanager
def _repository(settings: Settings) -> Iterator[SQLiteRepository]:
    repository = SQLiteRepository(
        db_path=settings.db_path,
        user_id=settings.user_context.user_id,
        user_name=settings.user_context.user_name,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    repository.init_schema()
    try:
        yield repository
    finally:
        repository.close()
