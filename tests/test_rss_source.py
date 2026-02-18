from __future__ import annotations

from datetime import UTC, datetime, timedelta

import allure

from news_recap.ingestion.sources.rss import RssFetchResponse, RssSource, RssSourceConfig

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Feed Intake & Cleaning"),
]


class _InMemoryFeedStateStore:
    def __init__(
        self, initial: dict[tuple[str, str], tuple[str | None, str | None]] | None = None
    ) -> None:
        self._data = dict(initial or {})
        self._snapshots: dict[tuple[str, str], tuple[str, str | None, datetime]] = {}

    def get_feed_http_cache(
        self, *, source_name: str, feed_url: str
    ) -> tuple[str | None, str | None]:
        return self._data.get((source_name, feed_url), (None, None))

    def upsert_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        self._data[(source_name, feed_url)] = (etag, last_modified)

    def get_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> tuple[str, str | None, datetime] | None:
        return self._snapshots.get((source_name, feed_set_hash))

    def upsert_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        snapshot_json: str,
        next_cursor: str | None,
    ) -> None:
        self._snapshots[(source_name, feed_set_hash)] = (
            snapshot_json,
            next_cursor,
            datetime.now(tz=UTC),
        )

    def update_rss_processing_snapshot_cursor(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        next_cursor: str | None,
    ) -> bool:
        snapshot = self._snapshots.get((source_name, feed_set_hash))
        if snapshot is None:
            return False
        snapshot_json, _, _ = snapshot
        self._snapshots[(source_name, feed_set_hash)] = (
            snapshot_json,
            next_cursor,
            datetime.now(tz=UTC),
        )
        return True

    def delete_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> None:
        self._snapshots.pop((source_name, feed_set_hash), None)


def test_rss_source_parses_description_only_item() -> None:
    source = RssSource(RssSourceConfig(feed_urls=("https://example.com/feed.xml",)))
    source._request_feed = (
        lambda *_args, **_kwargs: """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>France issues red flood alerts after ‘exceptional’ rainfall</title>
      <link>https://www.theguardian.com/world/2026/feb/17/red-flood-alerts-storm-nils-exceptional-rainfall</link>
      <description><![CDATA[<p><img src="https://i.guim.co.uk/test.jpg"></p><p>Aftermath of Storm Nils</p>]]></description>
      <pubDate>Tue, 17 Feb 2026 13:18:07 +0000</pubDate>
      <dc:creator>Ajit Niranjan</dc:creator>
      <guid isPermaLink="false">http://www.inoreader.com/article/3a9c6e7680c1e091</guid>
    </item>
  </channel>
</rss>
"""
    )

    page = source.fetch_page(cursor=None, limit=10)
    assert page.next_cursor is None
    assert len(page.articles) == 1

    article = page.articles[0]
    assert article.title.startswith("France issues red flood alerts")
    assert article.content is None
    assert article.summary is not None
    assert "Aftermath of Storm Nils" in article.summary
    assert article.published_at == datetime(2026, 2, 17, 13, 18, 7, tzinfo=UTC)
    assert article.external_id.endswith("http://www.inoreader.com/article/3a9c6e7680c1e091")


def test_rss_source_paginates_by_offset_cursor() -> None:
    source = RssSource(RssSourceConfig(feed_urls=("https://example.com/feed.xml",)))
    source._request_feed = (
        lambda *_args, **_kwargs: """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Item 1</title>
      <link>https://example.com/1</link>
      <pubDate>Tue, 17 Feb 2026 13:18:07 +0000</pubDate>
      <guid>id-1</guid>
    </item>
    <item>
      <title>Item 2</title>
      <link>https://example.com/2</link>
      <pubDate>Tue, 17 Feb 2026 12:18:07 +0000</pubDate>
      <guid>id-2</guid>
    </item>
    <item>
      <title>Item 3</title>
      <link>https://example.com/3</link>
      <pubDate>Tue, 17 Feb 2026 11:18:07 +0000</pubDate>
      <guid>id-3</guid>
    </item>
  </channel>
</rss>
"""
    )

    first_page = source.fetch_page(cursor=None, limit=2)
    assert [article.title for article in first_page.articles] == ["Item 1", "Item 2"]
    assert first_page.next_cursor == "2"

    second_page = source.fetch_page(cursor=first_page.next_cursor, limit=2)
    assert [article.title for article in second_page.articles] == ["Item 3"]
    assert second_page.next_cursor is None


def test_rss_source_pagination_uses_single_snapshot() -> None:
    source = RssSource(RssSourceConfig(feed_urls=("https://example.com/feed.xml",)))
    calls = 0

    first_snapshot = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item 1</title><link>https://example.com/1</link><pubDate>Tue, 17 Feb 2026 13:18:07 +0000</pubDate><guid>id-1</guid></item>
    <item><title>Item 2</title><link>https://example.com/2</link><pubDate>Tue, 17 Feb 2026 12:18:07 +0000</pubDate><guid>id-2</guid></item>
    <item><title>Item 3</title><link>https://example.com/3</link><pubDate>Tue, 17 Feb 2026 11:18:07 +0000</pubDate><guid>id-3</guid></item>
  </channel>
</rss>
"""
    second_snapshot = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>New Item</title><link>https://example.com/new</link><pubDate>Tue, 17 Feb 2026 14:18:07 +0000</pubDate><guid>id-new</guid></item>
  </channel>
</rss>
"""

    def _request_feed(_feed_url: str, **_kwargs: str | None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_snapshot
        return second_snapshot

    source._request_feed = _request_feed

    first_page = source.fetch_page(cursor=None, limit=2)
    second_page = source.fetch_page(cursor=first_page.next_cursor, limit=2)

    assert [article.title for article in first_page.articles] == ["Item 1", "Item 2"]
    assert [article.title for article in second_page.articles] == ["Item 3"]
    assert calls == 1


def test_rss_source_begin_run_resets_snapshot_between_runs() -> None:
    source = RssSource(RssSourceConfig(feed_urls=("https://example.com/feed.xml",)))
    calls = 0

    first_snapshot = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item A</title><link>https://example.com/a</link><guid>id-a</guid></item>
  </channel>
</rss>
"""
    second_snapshot = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item B</title><link>https://example.com/b</link><guid>id-b</guid></item>
  </channel>
</rss>
"""

    def _request_feed(_feed_url: str, **_kwargs: str | None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_snapshot
        return second_snapshot

    source._request_feed = _request_feed

    first_run_title = source.fetch_page(cursor=None, limit=1).articles[0].title
    source.begin_run()
    second_run_title = source.fetch_page(cursor=None, limit=1).articles[0].title

    assert first_run_title == "Item A"
    assert second_run_title == "Item B"
    assert calls == 2


def test_rss_source_external_id_is_stable_without_guid_and_with_invalid_pub_date() -> None:
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Item Without Guid</title>
      <link>https://example.com/no-guid</link>
      <pubDate>invalid-date</pubDate>
    </item>
  </channel>
</rss>
"""
    source_first = RssSource(RssSourceConfig(feed_urls=("https://example.com/feed.xml",)))
    source_first._request_feed = lambda *_args, **_kwargs: feed_xml

    source_second = RssSource(RssSourceConfig(feed_urls=("https://example.com/feed.xml",)))
    source_second._request_feed = lambda *_args, **_kwargs: feed_xml

    first_article = source_first.fetch_page(cursor=None, limit=10).articles[0]
    second_article = source_second.fetch_page(cursor=None, limit=10).articles[0]

    assert first_article.external_id == second_article.external_id
    assert first_article.external_id.startswith("generated:")
    assert first_article.published_at == datetime(1970, 1, 1, tzinfo=UTC)


def test_rss_source_uses_feed_cache_validators_and_skips_not_modified_response() -> None:
    store = _InMemoryFeedStateStore(
        {("rss", "https://example.com/feed.xml"): ('"etag-old"', "Tue, 17 Feb 2026 12:00:00 GMT")},
    )
    source = RssSource(
        RssSourceConfig(feed_urls=("https://example.com/feed.xml",), state_store=store),
    )
    seen_validators: list[tuple[str | None, str | None]] = []

    def _request_feed(
        _feed_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> RssFetchResponse:
        seen_validators.append((etag, last_modified))
        return RssFetchResponse(
            raw_xml=None,
            etag='"etag-new"',
            last_modified="Tue, 17 Feb 2026 13:00:00 GMT",
            not_modified=True,
        )

    source._request_feed = _request_feed

    page = source.fetch_page(cursor=None, limit=10)
    assert page.articles == []
    assert seen_validators == [('"etag-old"', "Tue, 17 Feb 2026 12:00:00 GMT")]
    stats = source.get_last_run_fetch_stats()
    assert stats.feeds_total == 1
    assert stats.requests_conditional == 1
    assert stats.responses_not_modified == 1
    assert stats.responses_fetched == 0
    assert stats.responses_with_etag == 1
    assert stats.responses_with_last_modified == 1
    assert stats.snapshot_articles == 0
    assert store.get_feed_http_cache(
        source_name="rss", feed_url="https://example.com/feed.xml"
    ) == (
        '"etag-new"',
        "Tue, 17 Feb 2026 13:00:00 GMT",
    )


def test_rss_source_saves_cache_headers_from_successful_response() -> None:
    store = _InMemoryFeedStateStore()
    source = RssSource(
        RssSourceConfig(feed_urls=("https://example.com/feed.xml",), state_store=store),
    )
    source._request_feed = lambda *_args, **_kwargs: RssFetchResponse(
        raw_xml="""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item A</title><link>https://example.com/a</link><guid>id-a</guid></item>
  </channel>
</rss>
""",
        etag='"etag-a"',
        last_modified="Tue, 17 Feb 2026 11:00:00 GMT",
    )

    page = source.fetch_page(cursor=None, limit=10)
    assert len(page.articles) == 1
    stats = source.get_last_run_fetch_stats()
    assert stats.feeds_total == 1
    assert stats.requests_conditional == 0
    assert stats.responses_not_modified == 0
    assert stats.responses_fetched == 1
    assert stats.responses_with_etag == 1
    assert stats.responses_with_last_modified == 1
    assert stats.snapshot_articles == 1
    assert store.get_feed_http_cache(
        source_name="rss", feed_url="https://example.com/feed.xml"
    ) == (
        '"etag-a"',
        "Tue, 17 Feb 2026 11:00:00 GMT",
    )


def test_rss_source_applies_items_limit_to_inoreader_stream_urls() -> None:
    source = RssSource(
        RssSourceConfig(
            feed_urls=("https://www.inoreader.com/stream/user/1/tag/world%20news",),
            default_items_per_feed=10_000,
            per_feed_items={
                "https://www.inoreader.com/stream/user/1/tag/world%20news": 4321,
            },
        ),
    )
    seen_urls: list[str] = []

    def _request_feed(
        feed_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> str:
        assert etag is None
        assert last_modified is None
        seen_urls.append(feed_url)
        return """<?xml version="1.0"?>
<rss version="2.0"><channel></channel></rss>
"""

    source._request_feed = _request_feed
    source.fetch_page(cursor=None, limit=10)

    assert seen_urls == ["https://www.inoreader.com/stream/user/1/tag/world%20news?n=4321"]


def test_rss_source_resumes_from_processing_snapshot_without_refetch() -> None:
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item 1</title><link>https://example.com/1</link><guid>id-1</guid></item>
    <item><title>Item 2</title><link>https://example.com/2</link><guid>id-2</guid></item>
    <item><title>Item 3</title><link>https://example.com/3</link><guid>id-3</guid></item>
  </channel>
</rss>
"""
    store = _InMemoryFeedStateStore()
    config = RssSourceConfig(
        feed_urls=("https://example.com/feed.xml",),
        state_store=store,
    )
    source_first = RssSource(config)
    source_first._request_feed = lambda *_args, **_kwargs: feed_xml

    first_page = source_first.fetch_page(cursor=None, limit=2)
    assert [article.title for article in first_page.articles] == ["Item 1", "Item 2"]
    assert first_page.next_cursor == "2"
    source_first.mark_page_processed(next_cursor=first_page.next_cursor)

    source_second = RssSource(config)
    source_second._request_feed = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Unexpected network fetch when resuming from snapshot"),
    )
    resumed_page = source_second.fetch_page(cursor=None, limit=2)
    assert [article.title for article in resumed_page.articles] == ["Item 3"]
    stats = source_second.get_last_run_fetch_stats()
    assert stats.snapshot_restored is True
    assert stats.resume_cursor == "2"
    source_second.mark_page_processed(next_cursor=resumed_page.next_cursor)

    source_third = RssSource(config)
    calls = 0

    def _request_feed_again(*_args: object, **_kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return feed_xml

    source_third._request_feed = _request_feed_again
    source_third.fetch_page(cursor=None, limit=1)
    assert calls == 1


def test_rss_source_drops_expired_processing_snapshot_and_fetches_fresh() -> None:
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item 1</title><link>https://example.com/1</link><guid>id-1</guid></item>
  </channel>
</rss>
"""
    store = _InMemoryFeedStateStore()
    config = RssSourceConfig(
        feed_urls=("https://example.com/feed.xml",),
        state_store=store,
        snapshot_max_age_seconds=60,
    )

    first = RssSource(config)
    first._request_feed = lambda *_args, **_kwargs: feed_xml
    first.fetch_page(cursor=None, limit=1)

    snapshot_key = (first.name, first._feed_set_hash)  # noqa: SLF001
    snapshot_json, next_cursor, _ = store._snapshots[snapshot_key]  # noqa: SLF001
    store._snapshots[snapshot_key] = (  # noqa: SLF001
        snapshot_json,
        next_cursor,
        datetime.now(tz=UTC) - timedelta(hours=1),
    )

    calls = 0
    second = RssSource(config)

    def _request_feed_again(*_args: object, **_kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return feed_xml

    second._request_feed = _request_feed_again
    second.fetch_page(cursor=None, limit=1)
    stats = second.get_last_run_fetch_stats()

    assert calls == 1
    assert stats.snapshot_expired is True
    assert stats.snapshot_restored is False


def test_rss_source_recreates_snapshot_when_cursor_update_row_missing() -> None:
    feed_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item><title>Item 1</title><link>https://example.com/1</link><guid>id-1</guid></item>
    <item><title>Item 2</title><link>https://example.com/2</link><guid>id-2</guid></item>
    <item><title>Item 3</title><link>https://example.com/3</link><guid>id-3</guid></item>
  </channel>
</rss>
"""
    store = _InMemoryFeedStateStore()
    config = RssSourceConfig(
        feed_urls=("https://example.com/feed.xml",),
        state_store=store,
    )
    source = RssSource(config)
    source._request_feed = lambda *_args, **_kwargs: feed_xml

    page = source.fetch_page(cursor=None, limit=2)
    snapshot_key = (source.name, source._feed_set_hash)  # noqa: SLF001
    del store._snapshots[snapshot_key]  # noqa: SLF001

    source.mark_page_processed(next_cursor=page.next_cursor)
    restored = store._snapshots.get(snapshot_key)  # noqa: SLF001
    assert restored is not None
    assert restored[1] == "2"
