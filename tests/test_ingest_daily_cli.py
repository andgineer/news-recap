from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from news_recap.ingestion.sources.rss import RssFetchResponse, RssSource
from news_recap.main import news_recap

_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Item 1</title>
      <link>https://example.com/1</link>
      <pubDate>Tue, 17 Feb 2026 13:18:07 +0000</pubDate>
      <guid>id-1</guid>
    </item>
  </channel>
</rss>
"""


def test_ingest_daily_shows_rss_conditional_get_stats(tmp_path: Path, monkeypatch) -> None:
    # Keep CLI test fully offline and fast: avoid loading remote HF model in dedup stage.
    monkeypatch.setenv("NEWS_RECAP_DEDUP_MODEL_NAME", "hashing-test")

    def _request_feed(
        _self: RssSource,
        _feed_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> RssFetchResponse:
        if etag is None and last_modified is None:
            return RssFetchResponse(
                raw_xml=_RSS_XML,
                etag='"etag-1"',
                last_modified="Tue, 17 Feb 2026 13:20:00 GMT",
            )
        return RssFetchResponse(
            raw_xml=None,
            etag='"etag-1"',
            last_modified="Tue, 17 Feb 2026 13:20:00 GMT",
            not_modified=True,
        )

    monkeypatch.setattr(RssSource, "_request_feed", _request_feed)

    db_path = tmp_path / "daily-cli.db"
    runner = CliRunner()

    first = runner.invoke(
        news_recap,
        [
            "ingest",
            "daily",
            "--db-path",
            str(db_path),
            "--feed-url",
            "https://example.com/feed.xml",
        ],
    )
    assert first.exit_code == 0
    assert (
        "RSS conditional GET: feeds=1 conditional=0 not_modified=0 fetched=1 "
        "received_etag=1 received_last_modified=1 snapshot_articles=1 "
        "snapshot_expired=no "
        "resumed_snapshot=no resume_cursor=-"
    ) in first.output
    assert (
        "feed=https://example.com/feed.xml items=10000 status=fetched "
        "if_none_match=no if_modified_since=no etag=yes last_modified=yes"
    ) in first.output

    second = runner.invoke(
        news_recap,
        [
            "ingest",
            "daily",
            "--db-path",
            str(db_path),
            "--feed-url",
            "https://example.com/feed.xml",
        ],
    )
    assert second.exit_code == 0
    assert (
        "RSS conditional GET: feeds=1 conditional=1 not_modified=1 fetched=0 "
        "received_etag=1 received_last_modified=1 snapshot_articles=0 "
        "snapshot_expired=no "
        "resumed_snapshot=no resume_cursor=-"
    ) in second.output
    assert (
        "feed=https://example.com/feed.xml items=10000 status=not_modified "
        "if_none_match=yes if_modified_since=yes etag=yes last_modified=yes"
    ) in second.output
