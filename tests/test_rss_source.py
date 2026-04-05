from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime, timedelta
from http.client import HTTPMessage
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from xml.etree.ElementTree import Element, SubElement

import allure
import pytest
from defusedxml import ElementTree

from news_recap.ingestion.sources.base import NonRetryableSourceError, TemporarySourceError
from news_recap.ingestion.sources.rss import (
    HTTP_NOT_MODIFIED,
    RETRYABLE_HTTP_STATUS_CODES,
    RssFetchResponse,
    RssSource,
    RssSourceConfig,
    _atom_link,
    _build_request_headers,
    _handle_http_error,
    _is_retryable_url_error,
    _normalize_header,
    _parse_atom,
    _parse_retry_after,
)

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


def test_build_request_headers_no_conditionals() -> None:
    headers = _build_request_headers(etag=None, last_modified=None)
    assert headers == {
        "Accept": "application/rss+xml, application/atom+xml, application/xml",
    }


def test_build_request_headers_with_if_none_match() -> None:
    headers = _build_request_headers(etag='"abc"', last_modified=None)
    assert headers["Accept"] == "application/rss+xml, application/atom+xml, application/xml"
    assert headers["If-None-Match"] == '"abc"'
    assert "If-Modified-Since" not in headers


def test_build_request_headers_with_if_modified_since() -> None:
    headers = _build_request_headers(etag=None, last_modified="Tue, 01 Apr 2026 12:00:00 GMT")
    assert headers["If-Modified-Since"] == "Tue, 01 Apr 2026 12:00:00 GMT"
    assert "If-None-Match" not in headers


def test_build_request_headers_with_etag_and_last_modified() -> None:
    headers = _build_request_headers(etag='"e"', last_modified="Wed, 02 Apr 2026 00:00:00 GMT")
    assert headers["If-None-Match"] == '"e"'
    assert headers["If-Modified-Since"] == "Wed, 02 Apr 2026 00:00:00 GMT"


def test_build_request_headers_skips_empty_strings() -> None:
    headers = _build_request_headers(etag="", last_modified="")
    assert headers == {
        "Accept": "application/rss+xml, application/atom+xml, application/xml",
    }


def test_handle_http_error_not_modified_returns_response() -> None:
    headers = HTTPMessage()
    headers["ETag"] = '"server-etag"'
    headers["Last-Modified"] = "Thu, 03 Apr 2026 10:00:00 GMT"
    error = HTTPError(
        "https://example.com/feed",
        HTTP_NOT_MODIFIED,
        "Not Modified",
        headers,
        BytesIO(b""),
    )
    response, temp_err = _handle_http_error(
        error=error,
        etag='"cached"',
        last_modified="Wed, 01 Jan 2020 00:00:00 GMT",
    )
    assert temp_err is None
    assert response is not None
    assert response.not_modified is True
    assert response.raw_xml is None
    assert response.etag == '"server-etag"'
    assert response.last_modified == "Thu, 03 Apr 2026 10:00:00 GMT"


def test_handle_http_error_not_modified_falls_back_to_request_validators() -> None:
    headers = HTTPMessage()
    error = HTTPError(
        "https://example.com/feed",
        HTTP_NOT_MODIFIED,
        "Not Modified",
        headers,
        BytesIO(b""),
    )
    response, temp_err = _handle_http_error(
        error=error,
        etag='"fallback-etag"',
        last_modified="Tue, 01 Apr 2026 12:00:00 GMT",
    )
    assert temp_err is None
    assert response is not None
    assert response.etag == '"fallback-etag"'
    assert response.last_modified == "Tue, 01 Apr 2026 12:00:00 GMT"


@pytest.mark.parametrize("status_code", sorted(RETRYABLE_HTTP_STATUS_CODES))
def test_handle_http_error_retryable_returns_temporary(status_code: int) -> None:
    headers = HTTPMessage()
    error = HTTPError(
        "https://example.com/feed",
        status_code,
        "Temporary",
        headers,
        BytesIO(b""),
    )
    response, temp_err = _handle_http_error(error=error, etag=None, last_modified=None)
    assert response is None
    assert isinstance(temp_err, TemporarySourceError)
    assert temp_err.code == str(status_code)
    assert str(status_code) in temp_err.message
    assert temp_err.retry_after is None


def test_handle_http_error_retryable_includes_retry_after() -> None:
    headers = HTTPMessage()
    headers["Retry-After"] = "90"
    error = HTTPError(
        "https://example.com/feed",
        503,
        "Service Unavailable",
        headers,
        BytesIO(b""),
    )
    _response, temp_err = _handle_http_error(error=error, etag=None, last_modified=None)
    assert isinstance(temp_err, TemporarySourceError)
    assert temp_err.retry_after == 90


def test_handle_http_error_non_retryable_raises() -> None:
    headers = HTTPMessage()
    error = HTTPError(
        "https://example.com/feed",
        404,
        "Not Found",
        headers,
        BytesIO(b""),
    )
    with pytest.raises(NonRetryableSourceError) as exc_info:
        _handle_http_error(error=error, etag=None, last_modified=None)
    assert exc_info.value.code == "404"
    assert exc_info.value.__cause__ is error


def test_parse_atom_single_entry() -> None:
    atom_xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Site</title>
  <entry>
    <title>Hello Atom</title>
    <link href="https://example.com/hello"/>
    <id>urn:uuid:entry-1</id>
    <summary>Short summary</summary>
    <content type="html">&lt;p&gt;Full body&lt;/p&gt;</content>
    <published>Mon, 01 Apr 2024 12:00:00 +0000</published>
    <author><name>Pat Author</name></author>
  </entry>
</feed>
"""
    root = ElementTree.fromstring(atom_xml)
    feed_url = "https://example.com/feed"
    articles = _parse_atom(root, feed_url)
    assert len(articles) == 1
    article = articles[0]
    assert article.title == "Hello Atom"
    assert article.url == "https://example.com/hello"
    assert article.summary == "Short summary"
    assert article.content == "<p>Full body</p>"
    assert article.source == "Pat Author"
    assert article.published_at == datetime(2024, 4, 1, 12, 0, 0, tzinfo=UTC)
    assert article.raw_payload["feed_url"] == feed_url
    assert article.raw_payload["id"] == "urn:uuid:entry-1"


def test_atom_link_prefers_alternate_over_self() -> None:
    entry = Element("entry")
    SubElement(entry, "link", {"rel": "self", "href": "https://example.com/self"})
    SubElement(entry, "link", {"rel": "alternate", "href": "https://example.com/article"})
    assert _atom_link(entry) == "https://example.com/article"


def test_atom_link_prefers_empty_rel() -> None:
    entry = Element("entry")
    SubElement(entry, "link", {"href": "https://example.com/default"})
    assert _atom_link(entry) == "https://example.com/default"


def test_atom_link_fallback_to_any_href() -> None:
    entry = Element("entry")
    SubElement(entry, "link", {"rel": "enclosure", "href": "https://example.com/file"})
    assert _atom_link(entry) == "https://example.com/file"


def test_atom_link_returns_none_without_href() -> None:
    entry = Element("entry")
    SubElement(entry, "link", {"rel": "alternate"})
    assert _atom_link(entry) is None


def test_parse_retry_after_none_and_empty() -> None:
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None


def test_parse_retry_after_invalid_returns_none() -> None:
    assert _parse_retry_after("not-a-number") is None


def test_parse_retry_after_seconds() -> None:
    assert _parse_retry_after("120") == 120


def test_normalize_header_none() -> None:
    assert _normalize_header(None) is None


def test_normalize_header_strips_whitespace() -> None:
    assert _normalize_header('  "etag"  ') == '"etag"'


def test_normalize_header_empty_string_returns_none() -> None:
    assert _normalize_header("   ") is None


# ---------------------------------------------------------------------------
# _is_retryable_url_error classification
# ---------------------------------------------------------------------------


def test_is_retryable_url_error_ssl_cert_failure() -> None:
    reason = ssl.SSLCertVerificationError("certificate verify failed")
    assert _is_retryable_url_error(URLError(reason)) is False


def test_is_retryable_url_error_unknown_host() -> None:
    reason = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    assert _is_retryable_url_error(URLError(reason)) is False


def test_is_retryable_url_error_dns_temporary() -> None:
    reason = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
    assert _is_retryable_url_error(URLError(reason)) is True


def test_is_retryable_url_error_connection_refused() -> None:
    assert _is_retryable_url_error(URLError(ConnectionRefusedError())) is True


def test_is_retryable_url_error_connection_reset() -> None:
    assert _is_retryable_url_error(URLError(ConnectionResetError())) is True


def test_is_retryable_url_error_generic_oserror() -> None:
    assert _is_retryable_url_error(URLError(OSError("Network is unreachable"))) is True


# ---------------------------------------------------------------------------
# _request_feed retry behaviour (integration through the real retry loop)
# ---------------------------------------------------------------------------

_FEED_URL = "https://example.com/feed.xml"


def _make_source(*, max_retries: int = 3) -> RssSource:
    return RssSource(
        RssSourceConfig(
            feed_urls=(_FEED_URL,),
            max_retries=max_retries,
            retry_backoff_seconds=0,
        )
    )


def test_request_feed_retries_on_timeout_error() -> None:
    source = _make_source(max_retries=3)
    with patch("news_recap.ingestion.sources.rss.urlopen", side_effect=TimeoutError):
        with pytest.raises(TemporarySourceError, match="timed out"):
            source._request_feed(_FEED_URL)


def test_request_feed_retries_on_connection_refused() -> None:
    source = _make_source(max_retries=2)
    mock_urlopen = patch(
        "news_recap.ingestion.sources.rss.urlopen",
        side_effect=URLError(ConnectionRefusedError()),
    )
    with mock_urlopen as m:
        with pytest.raises(TemporarySourceError, match="transport"):
            source._request_feed(_FEED_URL)
        assert m.call_count == 2


def test_request_feed_retries_on_http_503() -> None:
    source = _make_source(max_retries=2)
    error = HTTPError(_FEED_URL, 503, "Service Unavailable", HTTPMessage(), BytesIO(b""))
    mock_urlopen = patch(
        "news_recap.ingestion.sources.rss.urlopen",
        side_effect=error,
    )
    with mock_urlopen as m:
        with pytest.raises(TemporarySourceError, match="503"):
            source._request_feed(_FEED_URL)
        assert m.call_count == 2


def test_request_feed_no_retry_on_ssl_cert_error() -> None:
    source = _make_source(max_retries=3)
    reason = ssl.SSLCertVerificationError("certificate verify failed")
    mock_urlopen = patch(
        "news_recap.ingestion.sources.rss.urlopen",
        side_effect=URLError(reason),
    )
    with mock_urlopen as m:
        with pytest.raises(NonRetryableSourceError, match="transport"):
            source._request_feed(_FEED_URL)
        assert m.call_count == 1


def test_request_feed_no_retry_on_unknown_host() -> None:
    source = _make_source(max_retries=3)
    reason = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    mock_urlopen = patch(
        "news_recap.ingestion.sources.rss.urlopen",
        side_effect=URLError(reason),
    )
    with mock_urlopen as m:
        with pytest.raises(NonRetryableSourceError, match="transport"):
            source._request_feed(_FEED_URL)
        assert m.call_count == 1


def test_request_feed_no_retry_on_http_404() -> None:
    source = _make_source(max_retries=3)
    error = HTTPError(_FEED_URL, 404, "Not Found", HTTPMessage(), BytesIO(b""))
    mock_urlopen = patch(
        "news_recap.ingestion.sources.rss.urlopen",
        side_effect=error,
    )
    with mock_urlopen as m:
        with pytest.raises(NonRetryableSourceError, match="404"):
            source._request_feed(_FEED_URL)
        assert m.call_count == 1


def test_request_feed_retries_then_succeeds() -> None:
    """First attempt fails transiently, second succeeds."""
    source = _make_source(max_retries=3)
    response_cm = _FakeResponseCM(b"<rss><channel></channel></rss>")
    calls = [URLError(ConnectionResetError()), response_cm]
    with patch("news_recap.ingestion.sources.rss.urlopen", side_effect=calls) as m:
        result = source._request_feed(_FEED_URL)
        assert result.raw_xml == "<rss><channel></channel></rss>"
        assert m.call_count == 2


class _FakeResponseCM:
    """Minimal urlopen response context manager for testing."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = HTTPMessage()

    def __enter__(self) -> _FakeResponseCM:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def read(self) -> bytes:
        return self._body
