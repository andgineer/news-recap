from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import (
    IngestionRunCounters,
    NormalizedArticle,
    RunStatus,
    UpsertAction,
)
from news_recap.ingestion.repository import IngestionStore
from news_recap.storage.io import day_key, gc_old_days

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Persist & Run Accounting"),
]


def _article(
    *,
    external_id: str,
    text: str,
    title: str,
    published_at: datetime,
    url: str | None = None,
) -> NormalizedArticle:
    if url is None:
        url = f"https://example.com/news/{external_id}"
    canonical = canonicalize_url(url)
    return NormalizedArticle(
        source_name="inoreader",
        external_id=external_id,
        url=url,
        url_canonical=canonical,
        url_hash=url_hash(canonical),
        title=title,
        source_domain=extract_domain(canonical),
        published_at=published_at,
        language_detected="en",
        content_raw=f"<p>{text}</p>",
        summary_raw=None,
        is_full_content=True,
        needs_enrichment=False,
        clean_text=text,
        clean_text_chars=len(text),
        is_truncated=False,
    )


def test_start_run_rejects_parallel_runs_for_same_source(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)

    first_run_id = store.start_run(source="rss")
    assert first_run_id

    with pytest.raises(RuntimeError, match="already active"):
        store.start_run(source="rss")

    store.finish_run(
        run_id=first_run_id,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(),
    )
    second_run_id = store.start_run(source="rss")
    assert second_run_id
    store.close()


def test_start_run_recovers_stale_running_run(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)

    stale_run_id = store.start_run(source="rss")

    runs_store = store._load_runs()
    for run in runs_store.runs:
        if run.run_id == stale_run_id:
            run.heartbeat_at = datetime(2000, 1, 1, tzinfo=UTC)
    store._save_runs()
    store._runs = None

    new_run_id = store.start_run(source="rss", stale_after=timedelta(seconds=1))
    assert new_run_id != stale_run_id

    runs_store = store._load_runs()
    stale_run = next(r for r in runs_store.runs if r.run_id == stale_run_id)
    assert stale_run.status == RunStatus.FAILED.value
    assert "Auto-recovered stale running run" in str(stale_run.error_summary)
    assert stale_run.finished_at is not None
    store.close()


def test_distinct_external_ids_with_distinct_urls_insert_separately(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)
    run_id = store.start_run(source="inoreader")
    published_at = datetime.now(tz=UTC)

    first = store.upsert_article(
        article=_article(
            external_id="stable-1",
            text="first article",
            title="First",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    second = store.upsert_article(
        article=_article(
            external_id="stable-2",
            text="second article",
            title="Second",
            published_at=published_at,
        ),
        run_id=run_id,
    )

    assert first.action == UpsertAction.INSERTED
    assert second.action == UpsertAction.INSERTED

    articles = store._all_articles()
    assert len(articles) == 2
    assert articles[first.article_id].clean_text == "first article"
    assert articles[second.article_id].clean_text == "second article"
    store.close()


def test_url_canonical_fallback_merges_same_url_articles(tmp_path: Path) -> None:
    """Articles with different external_ids but the same canonical URL merge."""
    store = IngestionStore(tmp_path)
    run_id = store.start_run(source="inoreader")
    published_at = datetime.now(tz=UTC)
    shared_url = "https://example.com/news/item"

    first = store.upsert_article(
        article=_article(
            external_id="generated:a",
            text="draft text",
            title="Draft",
            published_at=published_at,
            url=shared_url,
        ),
        run_id=run_id,
    )
    second = store.upsert_article(
        article=_article(
            external_id="generated:b",
            text="updated text",
            title="Updated",
            published_at=published_at,
            url=shared_url,
        ),
        run_id=run_id,
    )

    assert first.action == UpsertAction.INSERTED
    assert second.action == UpsertAction.UPDATED

    articles = store._all_articles()
    assert len(articles) == 1
    merged = articles[first.article_id]
    assert merged.clean_text == "updated text"
    store.close()


def test_external_id_promotion_from_generated_to_stable(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)
    run_id = store.start_run(source="inoreader")
    published_at = datetime.now(tz=UTC)
    shared_url = "https://example.com/news/item"

    first = store.upsert_article(
        article=_article(
            external_id="generated:temp",
            text="initial text",
            title="Initial",
            published_at=published_at,
            url=shared_url,
        ),
        run_id=run_id,
    )
    second = store.upsert_article(
        article=_article(
            external_id="stable-1",
            text="final text",
            title="Final",
            published_at=published_at,
            url=shared_url,
        ),
        run_id=run_id,
    )
    third = store.upsert_article(
        article=_article(
            external_id="stable-1",
            text="final text",
            title="Final",
            published_at=published_at,
            url=shared_url,
        ),
        run_id=run_id,
    )

    assert first.action == UpsertAction.INSERTED
    assert second.action == UpsertAction.UPDATED
    assert third.action == UpsertAction.SKIPPED

    articles = store._all_articles()
    assert len(articles) == 1
    store.close()


def test_feed_http_cache_is_persisted_per_source_and_url(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)

    assert store.get_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
    ) == (None, None)

    store.upsert_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
        etag='"etag-1"',
        last_modified="Tue, 17 Feb 2026 12:00:00 GMT",
    )
    assert store.get_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
    ) == ('"etag-1"', "Tue, 17 Feb 2026 12:00:00 GMT")

    store.upsert_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
        etag='"etag-2"',
        last_modified="Tue, 17 Feb 2026 13:00:00 GMT",
    )
    assert store.get_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
    ) == ('"etag-2"', "Tue, 17 Feb 2026 13:00:00 GMT")

    store.close()


def test_processing_snapshot_state_is_persisted_and_can_be_advanced(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)

    assert (
        store.get_rss_processing_snapshot(
            source_name="rss",
            feed_set_hash="feed-set-hash",
        )
        is None
    )

    store.upsert_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
        snapshot_json='[{"external_id":"id-1"}]',
        next_cursor=None,
    )
    restored = store.get_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
    )
    assert restored is not None
    assert restored[:2] == ('[{"external_id":"id-1"}]', None)

    assert store.update_rss_processing_snapshot_cursor(
        source_name="rss",
        feed_set_hash="feed-set-hash",
        next_cursor="50",
    )
    advanced = store.get_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
    )
    assert advanced is not None
    assert advanced[:2] == ('[{"external_id":"id-1"}]', "50")

    store.delete_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
    )
    assert (
        store.get_rss_processing_snapshot(
            source_name="rss",
            feed_set_hash="feed-set-hash",
        )
        is None
    )
    assert (
        store.update_rss_processing_snapshot_cursor(
            source_name="rss",
            feed_set_hash="feed-set-hash",
            next_cursor="100",
        )
        is False
    )

    store.close()


def test_auto_gc_deletes_old_daily_partitions_on_init(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path, gc_retention_days=7)
    run_id = store.start_run(source="rss")
    now = datetime.now(tz=UTC)
    old_published_at = now - timedelta(days=10)

    store.upsert_article(
        article=_article(
            external_id="old-ext",
            text="old text",
            title="Old title",
            published_at=old_published_at,
        ),
        run_id=run_id,
    )
    store.finish_run(
        run_id=run_id,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(ingested_count=1),
    )
    store.close()

    old_dk = day_key(old_published_at)
    assert (tmp_path / "ingestion" / f"articles-{old_dk}.json").exists()

    reopened = IngestionStore(tmp_path, gc_retention_days=7)
    reopened.init_schema()
    assert not (tmp_path / "ingestion" / f"articles-{old_dk}.json").exists()


def test_gc_old_days_deletes_old_resource_directories(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    old_date = (today - timedelta(days=10)).isoformat()
    recent_date = (today - timedelta(days=3)).isoformat()

    res_dir = tmp_path / "resources"
    (res_dir / old_date).mkdir(parents=True)
    (res_dir / old_date / "art_1.json").write_text("{}", "utf-8")
    (res_dir / recent_date).mkdir(parents=True)
    (res_dir / recent_date / "art_2.json").write_text("{}", "utf-8")
    (res_dir / "not-a-date").mkdir(parents=True)

    deleted = gc_old_days(tmp_path, keep_days=7)
    assert res_dir / old_date in deleted
    assert not (res_dir / old_date).exists()
    assert (res_dir / recent_date).exists()
    assert (res_dir / "not-a-date").exists()
