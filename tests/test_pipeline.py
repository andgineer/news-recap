from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import allure
import pytest

from news_recap.config import DedupSettings, IngestionSettings, RssSettings, Settings
from news_recap.ingestion.models import (
    GapWrite,
    IngestionRunCounters,
    NormalizedArticle,
    RunStatus,
    SourceArticle,
    SourcePage,
)
from news_recap.ingestion.pipeline import run_daily_ingestion
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.ingestion.sources.base import (
    NonRetryableSourceError,
    TemporarySourceError,
)
from news_recap.ingestion.sources.rss import RssSource, RssSourceConfig

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Daily Run Observability"),
]


class StaticSource:
    name = "fake"

    def __init__(self, pages: dict[str | None, SourcePage]) -> None:
        self._pages = pages

    def fetch_page(self, cursor: str | None, limit: int) -> SourcePage:  # noqa: ARG002
        return self._pages.get(cursor, SourcePage(articles=[], next_cursor=None, cursor=cursor))


class FlakySource(StaticSource):
    def __init__(self, pages: dict[str | None, SourcePage]) -> None:
        super().__init__(pages)
        self._failed = False

    def fetch_page(self, cursor: str | None, limit: int) -> SourcePage:  # noqa: ARG002
        if cursor is None and not self._failed:
            self._failed = True
            raise TemporarySourceError(
                message="rate limited",
                code="429",
                from_cursor=cursor,
                retry_after=1,
            )
        return super().fetch_page(cursor, limit)


class NonRetryableFailingSource(StaticSource):
    def fetch_page(self, cursor: str | None, limit: int) -> SourcePage:  # noqa: ARG002
        raise NonRetryableSourceError(
            message="unauthorized",
            code="401",
            from_cursor=cursor,
        )


class CountingSource(StaticSource):
    def __init__(self, pages: dict[str | None, SourcePage]) -> None:
        super().__init__(pages)
        self.calls: list[str | None] = []

    def fetch_page(self, cursor: str | None, limit: int) -> SourcePage:  # noqa: ARG002
        self.calls.append(cursor)
        return super().fetch_page(cursor, limit)


class CheckpointingSource(StaticSource):
    def __init__(self, pages: dict[str | None, SourcePage]) -> None:
        super().__init__(pages)
        self.checkpoints: list[str | None] = []

    def mark_page_processed(self, *, next_cursor: str | None) -> None:
        self.checkpoints.append(next_cursor)


def _build_article(
    external_id: str,
    url: str,
    text: str,
    *,
    title: str = "Title",
) -> SourceArticle:
    now = datetime.now(tz=UTC)
    return SourceArticle(
        external_id=external_id,
        url=url,
        title=title,
        source="Source",
        published_at=now,
        content=f"<p>{text}</p>",
        summary=None,
        raw_payload={"id": external_id, "url": url},
    )


def _build_settings(db_path: Path) -> Settings:
    return Settings(
        db_path=db_path,
        ingestion=IngestionSettings(page_size=10, max_pages=5),
        dedup=DedupSettings(model_name="hashing-test", threshold=0.9),
        rss=RssSettings(feed_urls=("https://example.com/feed.xml",)),
    )


def test_pipeline_idempotent_run(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    pages = {
        None: SourcePage(
            articles=[
                _build_article("1", "https://example.com/1", "One repeated event"),
                _build_article("2", "https://mirror.example.com/2", "One repeated event"),
            ],
            next_cursor="cursor-1",
            cursor=None,
        ),
        "cursor-1": SourcePage(
            articles=[_build_article("3", "https://example.com/3", "Different event")],
            next_cursor=None,
            cursor="cursor-1",
        ),
    }
    source = StaticSource(pages)
    settings = _build_settings(db_path)

    first = run_daily_ingestion(settings=settings, repository=repository, source=source)
    second = run_daily_ingestion(settings=settings, repository=repository, source=source)

    assert first.status == RunStatus.SUCCEEDED
    assert first.counters.ingested_count == 3
    assert first.counters.dedup_duplicates_count >= 1

    assert second.status == RunStatus.SUCCEEDED
    assert second.counters.ingested_count == 0
    assert second.counters.updated_count == 0
    assert second.counters.skipped_count == 3

    repository.close()


def test_pipeline_backfills_open_gap(tmp_path: Path) -> None:
    db_path = tmp_path / "backfill.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    pages = {
        None: SourcePage(
            articles=[_build_article("1", "https://example.com/1", "Event")],
            next_cursor=None,
            cursor=None,
        )
    }
    source = FlakySource(pages)
    settings = _build_settings(db_path)

    first = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert first.status == RunStatus.PARTIAL
    assert first.counters.gaps_opened_count == 1
    assert len(repository.list_open_gaps(source=source.name, limit=10)) == 1

    second = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert second.status == RunStatus.SUCCEEDED
    assert second.counters.ingested_count == 1
    assert len(repository.list_open_gaps(source=source.name, limit=10)) == 0

    repository.close()


def test_pipeline_fails_fast_on_non_retryable_source_error(tmp_path: Path) -> None:
    db_path = tmp_path / "fail-fast.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    source = NonRetryableFailingSource({})
    settings = _build_settings(db_path)

    with pytest.raises(NonRetryableSourceError):
        run_daily_ingestion(settings=settings, repository=repository, source=source)

    assert len(repository.list_open_gaps(source=source.name, limit=10)) == 0
    last_run = repository._connection.execute(
        """
        SELECT status, gaps_opened_count
        FROM ingestion_runs
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    assert last_run is not None
    assert last_run["status"] == RunStatus.FAILED.value
    assert int(last_run["gaps_opened_count"]) == 0
    repository.close()


def test_pipeline_does_not_fetch_none_twice_when_gap_seed_is_none(tmp_path: Path) -> None:
    db_path = tmp_path / "dedupe-seed.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    setup_run_id = repository.start_run(source="fake")
    repository.create_gap(
        run_id=setup_run_id,
        source="fake",
        gap=GapWrite(
            from_cursor_or_time=None,
            to_cursor_or_time=None,
            error_code="429",
            retry_after=1,
        ),
    )
    repository.finish_run(
        run_id=setup_run_id,
        status=RunStatus.PARTIAL,
        counters=IngestionRunCounters(),
    )

    source = CountingSource(
        {
            None: SourcePage(
                articles=[_build_article("1", "https://example.com/1", "Event")],
                next_cursor=None,
                cursor=None,
            )
        }
    )
    settings = _build_settings(db_path)

    summary = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert summary.status == RunStatus.SUCCEEDED
    assert source.calls.count(None) == 1
    repository.close()


def test_pipeline_calls_source_page_checkpoint_after_successful_page(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoint-source.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    source = CheckpointingSource(
        {
            None: SourcePage(
                articles=[_build_article("1", "https://example.com/1", "Event One")],
                next_cursor="c1",
                cursor=None,
            ),
            "c1": SourcePage(
                articles=[_build_article("2", "https://example.com/2", "Event Two")],
                next_cursor=None,
                cursor="c1",
            ),
        }
    )
    settings = _build_settings(db_path)

    summary = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert summary.status == RunStatus.SUCCEEDED
    assert source.checkpoints == ["c1", None]
    repository.close()


def test_pipeline_dedup_does_not_merge_empty_clean_text_with_different_titles(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dedup-empty-clean.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    source = StaticSource(
        {
            None: SourcePage(
                articles=[
                    _build_article(
                        "1",
                        "https://example.com/1",
                        "",
                        title="Earthquake in Japan",
                    ),
                    _build_article(
                        "2",
                        "https://example.com/2",
                        "",
                        title="Bitcoin ETF gains in US",
                    ),
                ],
                next_cursor=None,
                cursor=None,
            ),
        },
    )
    settings = _build_settings(db_path)

    summary = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert summary.status == RunStatus.SUCCEEDED
    assert summary.counters.dedup_clusters_count == 2
    assert summary.counters.dedup_duplicates_count == 0
    repository.close()


def test_pipeline_dedup_keeps_merging_same_fact(tmp_path: Path) -> None:
    db_path = tmp_path / "dedup-same-fact.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    source = StaticSource(
        {
            None: SourcePage(
                articles=[
                    _build_article(
                        "1",
                        "https://example.com/1",
                        "Flood alerts issued.",
                        title="Storm Nils hits France",
                    ),
                    _build_article(
                        "2",
                        "https://example.com/2",
                        "Flood alerts issued.",
                        title="Storm Nils hits France",
                    ),
                ],
                next_cursor=None,
                cursor=None,
            ),
        },
    )
    settings = _build_settings(db_path)

    summary = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert summary.status == RunStatus.SUCCEEDED
    assert summary.counters.dedup_clusters_count == 1
    assert summary.counters.dedup_duplicates_count == 1
    repository.close()


def test_pipeline_max_pages_zero_means_unlimited(tmp_path: Path) -> None:
    db_path = tmp_path / "unlimited-pages.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    source = StaticSource(
        {
            None: SourcePage(
                articles=[_build_article("1", "https://example.com/1", "One")],
                next_cursor="c1",
                cursor=None,
            ),
            "c1": SourcePage(
                articles=[_build_article("2", "https://example.com/2", "Two")],
                next_cursor="c2",
                cursor="c1",
            ),
            "c2": SourcePage(
                articles=[_build_article("3", "https://example.com/3", "Three")],
                next_cursor=None,
                cursor="c2",
            ),
        },
    )
    settings = Settings(
        db_path=db_path,
        ingestion=IngestionSettings(page_size=1, max_pages=0),
        dedup=DedupSettings(model_name="hashing-test", threshold=0.9),
        rss=RssSettings(feed_urls=("https://example.com/feed.xml",)),
    )

    summary = run_daily_ingestion(settings=settings, repository=repository, source=source)
    assert summary.status == RunStatus.SUCCEEDED
    assert summary.counters.ingested_count == 3
    repository.close()


def test_pipeline_resumes_rss_processing_after_failure_without_refetch(tmp_path: Path) -> None:
    db_path = tmp_path / "rss-resume.db"
    repository = SQLiteRepository(db_path)
    repository.init_schema()

    feed_url = "https://example.com/feed.xml"
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item 1</title><link>https://example.com/1</link><pubDate>Tue, 17 Feb 2026 13:18:07 +0000</pubDate><guid>id-1</guid></item>
    <item><title>Item 2</title><link>https://example.com/2</link><pubDate>Tue, 17 Feb 2026 12:18:07 +0000</pubDate><guid>id-2</guid></item>
    <item><title>Item 3</title><link>https://example.com/3</link><pubDate>Tue, 17 Feb 2026 11:18:07 +0000</pubDate><guid>id-3</guid></item>
    <item><title>Item 4</title><link>https://example.com/4</link><pubDate>Tue, 17 Feb 2026 10:18:07 +0000</pubDate><guid>id-4</guid></item>
  </channel>
</rss>
"""

    settings = Settings(
        db_path=db_path,
        ingestion=IngestionSettings(page_size=2, max_pages=0),
        dedup=DedupSettings(model_name="hashing-test", threshold=0.9),
        rss=RssSettings(feed_urls=(feed_url,)),
    )

    source_first = RssSource(
        RssSourceConfig(
            feed_urls=(feed_url,),
            state_store=repository,
        ),
    )
    source_first._request_feed = lambda *_args, **_kwargs: feed_xml

    original_upsert = repository.upsert_article
    failed = {"done": False}

    def _flaky_upsert(*, article: NormalizedArticle, run_id: str) -> object:
        external_id = article.external_id
        if (not failed["done"]) and "id-3" in str(external_id):
            failed["done"] = True
            raise RuntimeError("simulated crash in article processing")
        return original_upsert(article=article, run_id=run_id)

    repository.upsert_article = _flaky_upsert  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_daily_ingestion(settings=settings, repository=repository, source=source_first)

    source_second = RssSource(
        RssSourceConfig(
            feed_urls=(feed_url,),
            state_store=repository,
        ),
    )
    source_second._request_feed = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Must resume from saved snapshot without network re-fetch"),
    )
    repository.upsert_article = original_upsert  # type: ignore[method-assign]

    resumed = run_daily_ingestion(settings=settings, repository=repository, source=source_second)
    assert resumed.status == RunStatus.SUCCEEDED
    assert resumed.counters.ingested_count == 2
    repository.close()
