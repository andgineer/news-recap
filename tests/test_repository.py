from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import (
    ClusterMember,
    DedupCluster,
    IngestionRunCounters,
    NormalizedArticle,
    RunStatus,
    UpsertAction,
)
from news_recap.ingestion.repository import SQLiteRepository

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Persist & Run Accounting"),
]


def _article(
    *, external_id: str, text: str, title: str, published_at: datetime
) -> NormalizedArticle:
    url = "https://example.com/news/item"
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
    repo = SQLiteRepository(tmp_path / "single-active-run.db")
    repo.init_schema()

    first_run_id = repo.start_run(source="rss")
    assert first_run_id

    with pytest.raises(RuntimeError, match="already active"):
        repo.start_run(source="rss")

    repo.finish_run(
        run_id=first_run_id,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(),
    )
    second_run_id = repo.start_run(source="rss")
    assert second_run_id
    repo.close()


def test_start_run_recovers_stale_running_run(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "stale-run.db")
    repo.init_schema()

    stale_run_id = repo.start_run(source="rss")
    repo._connection.execute(
        """
        UPDATE ingestion_runs
        SET heartbeat_at = ?
        WHERE run_id = ?
        """,
        ("2000-01-01 00:00:00", stale_run_id),
    )
    repo._connection.commit()

    new_run_id = repo.start_run(source="rss", stale_after=timedelta(seconds=1))
    assert new_run_id != stale_run_id

    stale_row = repo._connection.execute(
        """
        SELECT status, error_summary, finished_at
        FROM ingestion_runs
        WHERE run_id = ?
        """,
        (stale_run_id,),
    ).fetchone()
    assert stale_row is not None
    assert stale_row["status"] == RunStatus.FAILED.value
    assert "Auto-recovered stale running run" in str(stale_row["error_summary"])
    assert stale_row["finished_at"] is not None
    repo.close()


def test_stable_external_ids_do_not_merge_on_url_timestamp_match(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "stable-id.db")
    repo.init_schema()
    run_id = repo.start_run(source="inoreader")
    published_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    first = repo.upsert_article(
        article=_article(
            external_id="stable-1",
            text="first article",
            title="First",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    second = repo.upsert_article(
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

    count_row = repo._connection.execute("SELECT COUNT(*) AS cnt FROM articles").fetchone()
    assert count_row is not None
    assert int(count_row["cnt"]) == 2

    first_row = repo._connection.execute(
        "SELECT clean_text FROM articles WHERE source_name = ? AND external_id = ?",
        ("inoreader", "stable-1"),
    ).fetchone()
    second_row = repo._connection.execute(
        "SELECT clean_text FROM articles WHERE source_name = ? AND external_id = ?",
        ("inoreader", "stable-2"),
    ).fetchone()
    assert first_row is not None
    assert second_row is not None
    assert first_row["clean_text"] == "first article"
    assert second_row["clean_text"] == "second article"
    repo.close()


def test_generated_external_ids_use_url_timestamp_fallback(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "generated-id.db")
    repo.init_schema()
    run_id = repo.start_run(source="inoreader")
    published_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    first = repo.upsert_article(
        article=_article(
            external_id="generated:a",
            text="draft text",
            title="Draft",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    second = repo.upsert_article(
        article=_article(
            external_id="generated:b",
            text="updated text",
            title="Updated",
            published_at=published_at,
        ),
        run_id=run_id,
    )

    assert first.action == UpsertAction.INSERTED
    assert second.action == UpsertAction.UPDATED

    count_row = repo._connection.execute("SELECT COUNT(*) AS cnt FROM articles").fetchone()
    assert count_row is not None
    assert int(count_row["cnt"]) == 1

    row = repo._connection.execute(
        "SELECT external_id, clean_text FROM articles LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["external_id"] == "generated:a"
    assert row["clean_text"] == "updated text"

    alias_count = repo._connection.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM article_external_ids
        WHERE source_name = ?
        """,
        ("inoreader",),
    ).fetchone()
    assert alias_count is not None
    assert int(alias_count["cnt"]) == 2
    repo.close()


def test_generated_to_stable_external_id_promotes_to_same_article(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "promotion.db")
    repo.init_schema()
    run_id = repo.start_run(source="inoreader")
    published_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    first = repo.upsert_article(
        article=_article(
            external_id="generated:temp",
            text="initial text",
            title="Initial",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    second = repo.upsert_article(
        article=_article(
            external_id="stable-1",
            text="final text",
            title="Final",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    third = repo.upsert_article(
        article=_article(
            external_id="stable-1",
            text="final text",
            title="Final",
            published_at=published_at,
        ),
        run_id=run_id,
    )

    assert first.action == UpsertAction.INSERTED
    assert second.action == UpsertAction.UPDATED
    assert third.action == UpsertAction.SKIPPED

    count_row = repo._connection.execute("SELECT COUNT(*) AS cnt FROM articles").fetchone()
    assert count_row is not None
    assert int(count_row["cnt"]) == 1

    aliases = repo._connection.execute(
        """
        SELECT external_id
        FROM article_external_ids
        WHERE source_name = ?
        ORDER BY external_id
        """,
        ("inoreader",),
    ).fetchall()
    assert [str(item["external_id"]) for item in aliases] == ["generated:temp", "stable-1"]
    repo.close()


def test_foreign_keys_are_enabled_and_enforced(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "foreign-keys.db")
    repo.init_schema()

    pragma_row = repo._connection.execute("PRAGMA foreign_keys").fetchone()
    assert pragma_row is not None
    assert int(pragma_row[0]) == 1

    with pytest.raises(sqlite3.IntegrityError):
        repo._connection.execute(
            """
            INSERT INTO article_external_ids(
                source_name,
                external_id,
                article_id,
                is_primary,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("inoreader", "orphan", "missing-article-id", 0, datetime.now(tz=UTC).isoformat()),
        )
        repo._connection.commit()
    repo.close()


def test_article_dedup_requires_existing_cluster(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "dedup-fk.db")
    repo.init_schema()

    run_id = repo.start_run(source="inoreader")
    inserted = repo.upsert_article(
        article=_article(
            external_id="stable-1",
            text="some text",
            title="Some title",
            published_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        ),
        run_id=run_id,
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo._connection.execute(
            """
            INSERT INTO article_dedup(
                user_id,
                run_id,
                article_id,
                cluster_id,
                is_representative,
                similarity_to_rep
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "default_user",
                run_id,
                inserted.article_id,
                "cluster:missing",
                0,
                0.5,
            ),
        )
        repo._connection.commit()
    repo.close()


def test_fallback_key_has_db_level_uniqueness_for_generated_items(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "fallback-unique.db")
    repo.init_schema()

    fallback_key = "inoreader|hash-1|2026-01-01T10:00:00+00:00"
    repo._connection.execute(
        """
        INSERT INTO articles(
            article_id, source_name, external_id, url, url_canonical, url_hash,
            title, source_domain, published_at, language_detected, content_raw,
            summary_raw, is_full_content, clean_text,
            clean_text_chars, is_truncated, ingested_at, fallback_key, last_processed_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "article-1",
            "inoreader",
            "generated:first",
            "https://example.com/news/item",
            "https://example.com/news/item",
            "hash-1",
            "Title",
            "example.com",
            "2026-01-01T10:00:00+00:00",
            "en",
            "<p>x</p>",
            None,
            1,
            "x",
            1,
            0,
            datetime.now(tz=UTC).isoformat(),
            fallback_key,
            "run-1",
        ),
    )
    repo._connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        repo._connection.execute(
            """
            INSERT INTO articles(
                article_id, source_name, external_id, url, url_canonical, url_hash,
                title, source_domain, published_at, language_detected, content_raw,
                summary_raw, is_full_content, clean_text,
                clean_text_chars, is_truncated, ingested_at, fallback_key, last_processed_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "article-2",
                "inoreader",
                "generated:second",
                "https://example.com/news/item",
                "https://example.com/news/item",
                "hash-1",
                "Title2",
                "example.com",
                "2026-01-01T10:00:00+00:00",
                "en",
                "<p>y</p>",
                None,
                1,
                "y",
                1,
                0,
                datetime.now(tz=UTC).isoformat(),
                fallback_key,
                "run-2",
            ),
        )
        repo._connection.commit()
    repo.close()


def test_feed_http_cache_is_persisted_per_source_and_url(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "feed-cache.db")
    repo.init_schema()

    assert repo.get_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
    ) == (None, None)

    repo.upsert_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
        etag='"etag-1"',
        last_modified="Tue, 17 Feb 2026 12:00:00 GMT",
    )
    assert repo.get_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
    ) == ('"etag-1"', "Tue, 17 Feb 2026 12:00:00 GMT")

    repo.upsert_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
        etag='"etag-2"',
        last_modified="Tue, 17 Feb 2026 13:00:00 GMT",
    )
    assert repo.get_feed_http_cache(
        source_name="rss",
        feed_url="https://example.com/feed.xml",
    ) == ('"etag-2"', "Tue, 17 Feb 2026 13:00:00 GMT")

    repo.close()


def test_processing_snapshot_state_is_persisted_and_can_be_advanced(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "processing-snapshot.db")
    repo.init_schema()

    assert (
        repo.get_rss_processing_snapshot(
            source_name="rss",
            feed_set_hash="feed-set-hash",
        )
        is None
    )

    repo.upsert_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
        snapshot_json='[{"external_id":"id-1"}]',
        next_cursor=None,
    )
    restored = repo.get_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
    )
    assert restored is not None
    assert restored[:2] == ('[{"external_id":"id-1"}]', None)

    assert repo.update_rss_processing_snapshot_cursor(
        source_name="rss",
        feed_set_hash="feed-set-hash",
        next_cursor="50",
    )
    advanced = repo.get_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
    )
    assert advanced is not None
    assert advanced[:2] == ('[{"external_id":"id-1"}]', "50")

    repo.delete_rss_processing_snapshot(
        source_name="rss",
        feed_set_hash="feed-set-hash",
    )
    assert (
        repo.get_rss_processing_snapshot(
            source_name="rss",
            feed_set_hash="feed-set-hash",
        )
        is None
    )
    assert (
        repo.update_rss_processing_snapshot_cursor(
            source_name="rss",
            feed_set_hash="feed-set-hash",
            next_cursor="100",
        )
        is False
    )

    repo.close()


def test_prune_articles_removes_old_content_and_related_rows(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "retention-prune.db")
    repo.init_schema()
    run_id = repo.start_run(source="rss")

    now = datetime.now(tz=UTC)
    old_published_at = now - timedelta(days=45)
    fresh_published_at = now - timedelta(days=2)

    old_inserted = repo.upsert_article(
        article=_article(
            external_id="old-ext",
            text="old text",
            title="Old title",
            published_at=old_published_at,
        ),
        run_id=run_id,
    )
    fresh_inserted = repo.upsert_article(
        article=_article(
            external_id="fresh-ext",
            text="fresh text",
            title="Fresh title",
            published_at=fresh_published_at,
        ),
        run_id=run_id,
    )

    repo.upsert_raw_article(
        source_name="inoreader",
        external_id="old-ext",
        raw_payload={"id": "old-ext"},
    )
    repo.upsert_raw_article(
        source_name="inoreader",
        external_id="fresh-ext",
        raw_payload={"id": "fresh-ext"},
    )
    repo._connection.execute(
        "UPDATE articles_raw SET first_seen_at = ? WHERE source_name = ? AND external_id = ?",
        (old_published_at.isoformat(), "inoreader", "old-ext"),
    )
    repo._connection.execute(
        "UPDATE user_articles SET discovered_at = ? WHERE user_id = ? AND article_id = ?",
        (old_published_at.isoformat(), repo.user_id, old_inserted.article_id),
    )
    repo._connection.execute(
        "UPDATE user_articles SET discovered_at = ? WHERE user_id = ? AND article_id = ?",
        (fresh_published_at.isoformat(), repo.user_id, fresh_inserted.article_id),
    )
    repo._connection.commit()

    repo.save_dedup_clusters(
        run_id=run_id,
        model_name="hashing-test",
        threshold=0.95,
        clusters=[
            DedupCluster(
                cluster_id="cluster:old",
                representative_article_id=old_inserted.article_id,
                alt_sources=[],
                members=[
                    ClusterMember(
                        article_id=old_inserted.article_id,
                        similarity_to_representative=1.0,
                        is_representative=True,
                    ),
                ],
            ),
        ],
    )

    result = repo.prune_articles(cutoff=now - timedelta(days=30))
    assert result.articles_deleted == 1
    assert result.raw_payloads_deleted == 0

    article_count_after_prune = repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM articles"
    ).fetchone()
    assert article_count_after_prune is not None
    assert int(article_count_after_prune["cnt"]) == 2

    gc_result = repo.gc_unreferenced_articles()
    assert gc_result.articles_deleted == 1
    assert gc_result.raw_payloads_deleted == 1

    remaining_article = repo._connection.execute(
        "SELECT article_id, external_id FROM articles LIMIT 1"
    ).fetchone()
    assert remaining_article is not None
    assert remaining_article["article_id"] == fresh_inserted.article_id
    assert remaining_article["external_id"] == "fresh-ext"

    dedup_cluster_count = repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM dedup_clusters"
    ).fetchone()
    assert dedup_cluster_count is not None
    assert int(dedup_cluster_count["cnt"]) == 0

    dedup_member_count = repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM article_dedup"
    ).fetchone()
    assert dedup_member_count is not None
    assert int(dedup_member_count["cnt"]) == 0

    raw_count = repo._connection.execute("SELECT COUNT(*) AS cnt FROM articles_raw").fetchone()
    assert raw_count is not None
    assert int(raw_count["cnt"]) == 1
    repo.close()


def test_prune_articles_keeps_raw_when_article_is_recent_even_if_raw_is_old(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "retention-raw-kept.db")
    repo.init_schema()
    run_id = repo.start_run(source="rss")

    now = datetime.now(tz=UTC)
    fresh_published_at = now - timedelta(days=2)

    repo.upsert_article(
        article=_article(
            external_id="fresh-ext",
            text="fresh text",
            title="Fresh title",
            published_at=fresh_published_at,
        ),
        run_id=run_id,
    )
    repo.upsert_raw_article(
        source_name="inoreader",
        external_id="fresh-ext",
        raw_payload={"id": "fresh-ext"},
    )
    repo._connection.execute(
        "UPDATE articles_raw SET first_seen_at = ? WHERE source_name = ? AND external_id = ?",
        ((now - timedelta(days=90)).isoformat(), "inoreader", "fresh-ext"),
    )
    repo._connection.commit()

    result = repo.prune_articles(cutoff=now - timedelta(days=30))
    assert result.articles_deleted == 0
    assert result.raw_payloads_deleted == 0

    row = repo._connection.execute("SELECT COUNT(*) AS cnt FROM articles_raw").fetchone()
    assert row is not None
    assert int(row["cnt"]) == 1
    repo.close()


def test_shared_articles_are_reused_across_users_and_deleted_after_last_unlink(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "shared-articles.db"
    published_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    first_repo = SQLiteRepository(db_path, user_id="user_a", user_name="User A")
    first_repo.init_schema()
    first_run = first_repo.start_run(source="rss")
    first_result = first_repo.upsert_article(
        article=_article(
            external_id="stable-1",
            text="same global article",
            title="Shared article",
            published_at=published_at,
        ),
        run_id=first_run,
    )
    assert first_result.action == UpsertAction.INSERTED
    first_repo.finish_run(
        run_id=first_run,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(ingested_count=1),
    )
    first_repo.close()

    second_repo = SQLiteRepository(db_path, user_id="user_b", user_name="User B")
    second_repo.init_schema()
    second_run = second_repo.start_run(source="rss")
    second_result = second_repo.upsert_article(
        article=_article(
            external_id="stable-1",
            text="same global article",
            title="Shared article",
            published_at=published_at,
        ),
        run_id=second_run,
    )
    assert second_result.action == UpsertAction.INSERTED
    second_repo.finish_run(
        run_id=second_run,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(ingested_count=1),
    )

    article_count = second_repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM articles"
    ).fetchone()
    assert article_count is not None
    assert int(article_count["cnt"]) == 1

    links_count = second_repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM user_articles"
    ).fetchone()
    assert links_count is not None
    assert int(links_count["cnt"]) == 2

    cutoff = datetime.now(tz=UTC)
    second_prune = second_repo.prune_articles(cutoff=cutoff)
    assert second_prune.articles_deleted == 1

    after_second_prune = second_repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM articles"
    ).fetchone()
    assert after_second_prune is not None
    assert int(after_second_prune["cnt"]) == 1
    second_repo.close()

    first_repo_again = SQLiteRepository(db_path, user_id="user_a", user_name="User A")
    first_repo_again.init_schema()
    first_prune = first_repo_again.prune_articles(cutoff=cutoff)
    assert first_prune.articles_deleted == 1

    gc_result = first_repo_again.gc_unreferenced_articles()
    assert gc_result.articles_deleted == 1

    final_count = first_repo_again._connection.execute(
        "SELECT COUNT(*) AS cnt FROM articles"
    ).fetchone()
    assert final_count is not None
    assert int(final_count["cnt"]) == 0
    first_repo_again.close()


def test_article_resource_lookup_prefers_private_then_public(tmp_path: Path) -> None:
    db_path = tmp_path / "article-resources.db"
    canonical = canonicalize_url("https://example.com/news/1")
    hashed = url_hash(canonical)

    repo_a = SQLiteRepository(db_path, user_id="user_a", user_name="User A")
    repo_a.init_schema()
    repo_a.upsert_public_article_resource(
        url_hash=hashed,
        url_canonical=canonical,
        fetch_status="ok",
        http_status=200,
        content_text="public-content",
        fetched_at=datetime.now(tz=UTC),
    )

    public_view = repo_a.get_article_resource_for_user(url_hash=hashed)
    assert public_view is not None
    assert public_view.user_id is None
    assert public_view.content_text == "public-content"

    repo_a.upsert_user_article_resource(
        url_hash=hashed,
        url_canonical=canonical,
        fetch_status="ok",
        http_status=200,
        content_text="private-a",
        fetched_at=datetime.now(tz=UTC),
    )

    private_a_view = repo_a.get_article_resource_for_user(url_hash=hashed)
    assert private_a_view is not None
    assert private_a_view.user_id == "user_a"
    assert private_a_view.content_text == "private-a"

    repo_a.upsert_user_article_resource(
        url_hash=hashed,
        url_canonical=canonical,
        fetch_status="ok",
        http_status=200,
        content_text="expired-private-a",
        fetched_at=datetime.now(tz=UTC),
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    fallback_to_public = repo_a.get_article_resource_for_user(url_hash=hashed)
    assert fallback_to_public is not None
    assert fallback_to_public.user_id is None
    assert fallback_to_public.content_text == "public-content"

    repo_b = SQLiteRepository(db_path, user_id="user_b", user_name="User B")
    repo_b.init_schema()

    user_b_view_before_private = repo_b.get_article_resource_for_user(url_hash=hashed)
    assert user_b_view_before_private is not None
    assert user_b_view_before_private.user_id is None
    assert user_b_view_before_private.content_text == "public-content"

    repo_b.upsert_user_article_resource(
        url_hash=hashed,
        url_canonical=canonical,
        fetch_status="ok",
        http_status=200,
        content_text="private-b",
        fetched_at=datetime.now(tz=UTC),
    )
    user_b_view_after_private = repo_b.get_article_resource_for_user(url_hash=hashed)
    assert user_b_view_after_private is not None
    assert user_b_view_after_private.user_id == "user_b"
    assert user_b_view_after_private.content_text == "private-b"

    rows = repo_b._connection.execute(
        "SELECT COUNT(*) AS cnt FROM article_resources WHERE url_hash = ?",
        (hashed,),
    ).fetchone()
    assert rows is not None
    assert int(rows["cnt"]) == 3

    repo_b.close()
    repo_a.close()


def test_prune_articles_deletes_old_user_private_resources(tmp_path: Path) -> None:
    db_path = tmp_path / "prune-private-resources.db"
    repo = SQLiteRepository(db_path, user_id="user_a", user_name="User A")
    repo.init_schema()

    now = datetime.now(tz=UTC)
    old = now - timedelta(days=40)
    canonical = canonicalize_url("https://example.com/news/private-cache")
    hashed = url_hash(canonical)

    repo.upsert_user_article_resource(
        url_hash=hashed,
        url_canonical=canonical,
        fetch_status="ok",
        http_status=200,
        content_text="private-old",
        fetched_at=old,
    )
    repo._connection.execute(
        "UPDATE article_resources SET updated_at = ? WHERE user_id = ? AND url_hash = ?",
        (old.isoformat(), repo.user_id, hashed),
    )
    repo._connection.commit()

    result = repo.prune_articles(cutoff=now - timedelta(days=30))
    assert result.private_resources_deleted == 1

    remaining = repo._connection.execute(
        "SELECT COUNT(*) AS cnt FROM article_resources WHERE user_id = ?",
        (repo.user_id,),
    ).fetchone()
    assert remaining is not None
    assert int(remaining["cnt"]) == 0
    repo.close()
