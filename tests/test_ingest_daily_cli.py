from __future__ import annotations

from pathlib import Path

import allure
from click.testing import CliRunner

from news_recap.ingestion.sources.rss import RssFetchResponse, RssSource
from news_recap.main import news_recap

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Daily Run Observability"),
]

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
    data_dir = tmp_path / "daily-cli-data"
    monkeypatch.setenv("NEWS_RECAP_DEDUP_MODEL_NAME", "hashing-test")
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(data_dir))

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

    runner = CliRunner()

    first = runner.invoke(
        news_recap,
        ["--no-color", "ingest", "--rss", "https://example.com/feed.xml"],
    )
    assert first.exit_code == 0
    assert "Ingestion completed" in first.output
    assert "succeeded" in first.output
    assert "Ingested" in first.output
    assert "1/10000 items" in first.output
    assert "https://example.com/feed.xml" in first.output
    assert "fetched" in first.output
    assert "conditional=0/1" in first.output

    second = runner.invoke(
        news_recap,
        ["--no-color", "ingest", "--rss", "https://example.com/feed.xml"],
    )
    assert second.exit_code == 0
    assert "succeeded" in second.output
    assert "0/10000 items" in second.output
    assert "not_modified" in second.output
    assert "conditional=1/1" in second.output
    assert "not-modified=1" in second.output
