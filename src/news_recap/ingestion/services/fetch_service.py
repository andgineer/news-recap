"""Fetch/backfill stage for ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from news_recap.config import IngestionSettings
from news_recap.ingestion.models import GapWrite, IngestionRunCounters, UpsertAction
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.ingestion.services.normalize_service import ArticleNormalizationService
from news_recap.ingestion.sources.base import (
    PageCheckpointSourceAdapter,
    RunLifecycleSourceAdapter,
    SourceAdapter,
    TemporarySourceError,
)


@dataclass(slots=True)
class SeedCursor:
    """Cursor seed used to process one source chain."""

    cursor: str | None
    gap_id: int | None


class FetchStageService:
    """Fetches source pages, handles gaps, and persists normalized articles."""

    def __init__(
        self,
        *,
        source: SourceAdapter,
        repository: SQLiteRepository,
        ingestion_settings: IngestionSettings,
        normalizer: ArticleNormalizationService,
    ) -> None:
        self.source = source
        self.repository = repository
        self.ingestion_settings = ingestion_settings
        self.normalizer = normalizer

    def run(self, *, run_id: str, counters: IngestionRunCounters) -> None:
        if isinstance(self.source, RunLifecycleSourceAdapter):
            self.source.begin_run()

        open_gaps = self.repository.list_open_gaps(
            source=self.source.name,
            limit=self.ingestion_settings.backfill_max_gaps,
        )
        seeds = [SeedCursor(cursor=gap.from_cursor_or_time, gap_id=gap.gap_id) for gap in open_gaps]
        if all(seed.cursor is not None for seed in seeds):
            seeds.append(SeedCursor(cursor=None, gap_id=None))

        seen_cursors: set[str | None] = set()
        for seed in seeds:
            self._drain_chain(
                run_id=run_id,
                seed=seed,
                seen_cursors=seen_cursors,
                counters=counters,
            )

    def _drain_chain(
        self,
        *,
        run_id: str,
        seed: SeedCursor,
        seen_cursors: set[str | None],
        counters: IngestionRunCounters,
    ) -> None:
        cursor = seed.cursor
        pages_left = self.ingestion_settings.max_pages
        unlimited_pages = pages_left <= 0
        gap_resolved = False

        while unlimited_pages or pages_left > 0:
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            if not unlimited_pages:
                pages_left -= 1

            self.repository.touch_run(run_id)
            try:
                page = self.source.fetch_page(
                    cursor=cursor,
                    limit=self.ingestion_settings.page_size,
                )
            except TemporarySourceError as error:
                self.repository.create_gap(
                    run_id=run_id,
                    source=self.source.name,
                    gap=GapWrite(
                        from_cursor_or_time=error.from_cursor or cursor,
                        to_cursor_or_time=error.to_cursor,
                        error_code=error.code,
                        retry_after=error.retry_after,
                    ),
                )
                counters.gaps_opened_count += 1
                break

            if seed.gap_id and not gap_resolved:
                self.repository.resolve_gap(seed.gap_id)
                gap_resolved = True

            for source_article in page.articles:
                normalized = self.normalizer.normalize(source_article)
                result = self.repository.upsert_article(article=normalized, run_id=run_id)
                self.repository.upsert_raw_article(
                    source_name=self.source.name,
                    external_id=source_article.external_id,
                    raw_payload=source_article.raw_payload,
                    article_id=result.article_id,
                )
                if result.action == UpsertAction.INSERTED:
                    counters.ingested_count += 1
                elif result.action == UpsertAction.UPDATED:
                    counters.updated_count += 1
                else:
                    counters.skipped_count += 1

            self._mark_page_processed(next_cursor=page.next_cursor)
            self.repository.touch_run(run_id)

            cursor = page.next_cursor
            if not cursor:
                break

    def _mark_page_processed(self, *, next_cursor: str | None) -> None:
        if isinstance(self.source, PageCheckpointSourceAdapter):
            self.source.mark_page_processed(next_cursor=next_cursor)
