"""End-to-end ingestion pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from news_recap.config import Settings
from news_recap.ingestion.models import IngestionRunCounters, RunStatus
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.ingestion.services.dedup_service import DedupStageService
from news_recap.ingestion.services.fetch_service import FetchStageService
from news_recap.ingestion.services.normalize_service import ArticleNormalizationService
from news_recap.ingestion.sources.base import SourceAdapter


@dataclass(slots=True)
class IngestionSummary:
    """Result of one ingestion pipeline run."""

    run_id: str
    status: RunStatus
    counters: IngestionRunCounters


class IngestionOrchestrator:
    """Coordinates independent ingestion stage services."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: SQLiteRepository,
        source: SourceAdapter,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.source = source

        normalizer = ArticleNormalizationService(
            source_name=source.name,
            ingestion_settings=settings.ingestion,
        )
        self.fetch_stage = FetchStageService(
            source=source,
            repository=repository,
            ingestion_settings=settings.ingestion,
            normalizer=normalizer,
        )
        self.dedup_stage = DedupStageService(
            repository=repository,
            dedup_settings=settings.dedup,
        )

    def run_daily(self) -> IngestionSummary:
        counters = IngestionRunCounters()
        run_id = self.repository.start_run(
            source=self.source.name,
            stale_after=timedelta(seconds=self.settings.ingestion.active_run_stale_after_seconds),
        )

        try:
            self.repository.touch_run(run_id)
            self.fetch_stage.run(run_id=run_id, counters=counters)
            self.repository.touch_run(run_id)
            self.dedup_stage.run(run_id=run_id, counters=counters)

            final_status = RunStatus.PARTIAL if counters.gaps_opened_count else RunStatus.SUCCEEDED
            self.repository.finish_run(
                run_id=run_id,
                status=final_status,
                counters=counters,
            )
            return IngestionSummary(run_id=run_id, status=final_status, counters=counters)
        except Exception as exc:
            self.repository.finish_run(
                run_id=run_id,
                status=RunStatus.FAILED,
                counters=counters,
                error_summary=str(exc),
            )
            raise


def run_daily_ingestion(
    *,
    settings: Settings,
    repository: SQLiteRepository,
    source: SourceAdapter,
) -> IngestionSummary:
    """Run daily ingestion with provided dependencies."""

    return IngestionOrchestrator(
        settings=settings,
        repository=repository,
        source=source,
    ).run_daily()
