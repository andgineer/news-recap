"""Tests for ResourceLoader, ResourceCache, and load_resource_texts."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.loaders.resource_cache import ResourceCache
from news_recap.recap.loaders.resource_loader import LoadedResource, ResourceLoader
from news_recap.recap.storage.pipeline_io import load_cached_resource_texts, load_resource_texts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(url: str = "https://example.com", text: str = "x" * 500) -> LoadedResource:
    return LoadedResource(url=url, text=text, content_type="text/html", is_success=True)


def _fail(url: str = "https://example.com", error: str = "timeout") -> LoadedResource:
    return LoadedResource(url=url, text="", content_type="", is_success=False, error=error)


def _blocked(url: str = "https://youtube.com/watch?v=abc") -> LoadedResource:
    from news_recap.http.youtube_extractor import IP_BLOCKED_ERROR

    return LoadedResource(
        url=url,
        text="",
        content_type="youtube/transcript",
        is_success=False,
        error=IP_BLOCKED_ERROR,
    )


def _entry(sid: str, url: str = "https://example.com/a") -> ArticleIndexEntry:
    return ArticleIndexEntry(source_id=sid, title=f"Title {sid}", url=url, source="test")


# ===========================================================================
# ResourceLoader tests
# ===========================================================================


class TestResourceLoaderSingle:
    def test_load_html_success(self) -> None:
        fetcher = MagicMock()
        fetcher.fetch.return_value = MagicMock(
            is_success=True,
            content="<html><body><article><p>" + "word " * 200 + "</p></article></body></html>",
            content_type="text/html",
        )
        loader = ResourceLoader(fetcher=fetcher, max_chars=50_000)
        result = loader.load("https://example.com/article")
        assert result.is_success
        assert result.content_type == "text/html"

    def test_load_html_fetch_failure(self) -> None:
        fetcher = MagicMock()
        fetcher.fetch.return_value = MagicMock(
            is_success=False,
            content="",
            content_type="text/html",
            error="HTTP 403",
        )
        loader = ResourceLoader(fetcher=fetcher)
        result = loader.load("https://example.com/blocked")
        assert not result.is_success
        assert result.error == "HTTP 403"

    @patch("news_recap.recap.loaders.resource_loader.fetch_transcript")
    def test_load_youtube_success(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = MagicMock(
            is_success=True,
            text="Hello from YouTube",
            language="en",
        )
        loader = ResourceLoader()
        result = loader.load("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result.is_success
        assert result.content_type.startswith("youtube/transcript")
        assert "Hello from YouTube" in result.text

    @patch("news_recap.recap.loaders.resource_loader.fetch_transcript")
    def test_load_youtube_not_available(self, mock_fetch: MagicMock) -> None:
        from news_recap.http.youtube_extractor import NO_TRANSCRIPTS_ERROR

        mock_fetch.return_value = MagicMock(
            is_success=False,
            text="",
            language="",
            error=NO_TRANSCRIPTS_ERROR,
        )
        loader = ResourceLoader()
        result = loader.load("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert not result.is_success
        assert result.error == NO_TRANSCRIPTS_ERROR

    def test_load_autodetects_youtube_vs_html(self) -> None:
        fetcher = MagicMock()
        fetcher.fetch.return_value = MagicMock(
            is_success=True,
            content="<html><body><p>text</p></body></html>",
            content_type="text/html",
        )
        loader = ResourceLoader(fetcher=fetcher)
        result = loader.load("https://example.com/page")
        fetcher.fetch.assert_called_once()
        assert result.content_type == "text/html"


class TestResourceLoaderBatch:
    def test_load_batch_concurrent(self) -> None:
        fetcher = MagicMock()
        fetcher.fetch.return_value = MagicMock(
            is_success=True,
            content="<html><body><article><p>" + "content " * 100 + "</p></article></body></html>",
            content_type="text/html",
        )
        loader = ResourceLoader(fetcher=fetcher, max_workers=3)
        entries = [
            ("a1", "https://example.com/1"),
            ("a2", "https://example.com/2"),
            ("a3", "https://other.com/3"),
        ]
        results = loader.load_batch(entries)
        assert set(results.keys()) == {"a1", "a2", "a3"}
        assert fetcher.fetch.call_count == 3

    def test_load_batch_partial_failure(self) -> None:
        call_count = {"n": 0}

        def _fake_fetch(url: str):
            call_count["n"] += 1
            if "fail" in url:
                return MagicMock(is_success=False, content="", content_type="", error="HTTP 500")
            return MagicMock(
                is_success=True,
                content="<html><body><p>ok</p></body></html>",
                content_type="text/html",
            )

        fetcher = MagicMock()
        fetcher.fetch.side_effect = _fake_fetch
        loader = ResourceLoader(fetcher=fetcher, max_workers=2)
        entries = [
            ("ok1", "https://example.com/ok"),
            ("bad1", "https://example.com/fail"),
        ]
        results = loader.load_batch(entries)
        assert len(results) == 2
        assert not results["bad1"].is_success
        assert results["bad1"].error == "HTTP 500"

    def test_load_batch_respects_domain_semaphore(self) -> None:
        """Verify that at most max_per_domain requests run concurrently per domain."""
        max_concurrent: dict[str, int] = {"peak": 0}
        active = {"count": 0}
        lock = threading.Lock()

        def _slow_fetch(url: str):
            with lock:
                active["count"] += 1
                if active["count"] > max_concurrent["peak"]:
                    max_concurrent["peak"] = active["count"]
            time.sleep(0.05)
            with lock:
                active["count"] -= 1
            return MagicMock(
                is_success=True,
                content="<html><body><p>text</p></body></html>",
                content_type="text/html",
            )

        fetcher = MagicMock()
        fetcher.fetch.side_effect = _slow_fetch
        loader = ResourceLoader(fetcher=fetcher, max_workers=10, max_per_domain=2)
        entries = [(f"a{i}", f"https://same.com/{i}") for i in range(6)]
        results = loader.load_batch(entries)
        assert len(results) == 6
        assert max_concurrent["peak"] <= 2

    @patch("news_recap.recap.loaders.resource_loader.fetch_transcript")
    def test_youtube_batch_aborts_on_ip_block(self, mock_fetch: MagicMock) -> None:
        """When YouTube blocks us, remaining videos are not fetched."""
        from news_recap.http.youtube_extractor import IP_BLOCKED_ERROR, TranscriptResult

        call_count = {"n": 0}

        def _fake_transcript(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                return TranscriptResult(
                    text="",
                    language="",
                    is_success=False,
                    error=IP_BLOCKED_ERROR,
                )
            return TranscriptResult(text="ok", language="en", is_success=True)

        mock_fetch.side_effect = _fake_transcript
        loader = ResourceLoader(yt_delay=0, min_yt_seconds=0)
        entries = [
            ("yt1", "https://www.youtube.com/watch?v=aaaaaaaaa01"),
            ("yt2", "https://www.youtube.com/watch?v=aaaaaaaaa02"),
            ("yt3", "https://www.youtube.com/watch?v=aaaaaaaaa03"),
            ("yt4", "https://www.youtube.com/watch?v=aaaaaaaaa04"),
        ]
        results = loader.load_batch(entries)
        assert results["yt1"].is_success
        assert results["yt2"].is_blocked
        assert "yt3" not in results
        assert "yt4" not in results
        assert call_count["n"] == 2

    @patch("news_recap.recap.loaders.resource_loader.fetch_transcript")
    def test_youtube_stops_when_html_finishes(self, mock_fetch: MagicMock) -> None:
        """YouTube thread stops when HTML is done — not all videos need to be fetched."""
        from news_recap.http.youtube_extractor import TranscriptResult

        call_count = {"n": 0}

        def _slow_transcript(url, **kwargs):
            call_count["n"] += 1
            time.sleep(0.05)
            return TranscriptResult(text="ok", language="en", is_success=True)

        mock_fetch.side_effect = _slow_transcript

        fetcher = MagicMock()
        fetcher.fetch.return_value = MagicMock(
            is_success=True,
            content="<html><body><p>text</p></body></html>",
            content_type="text/html",
        )
        loader = ResourceLoader(fetcher=fetcher, yt_delay=0.5, min_yt_seconds=0)
        entries = [
            ("h1", "https://example.com/1"),
            ("yt1", "https://www.youtube.com/watch?v=aaaaaaaaa01"),
            ("yt2", "https://www.youtube.com/watch?v=aaaaaaaaa02"),
            ("yt3", "https://www.youtube.com/watch?v=aaaaaaaaa03"),
            ("yt4", "https://www.youtube.com/watch?v=aaaaaaaaa04"),
            ("yt5", "https://www.youtube.com/watch?v=aaaaaaaaa05"),
        ]
        results = loader.load_batch(entries)
        assert "h1" in results
        assert call_count["n"] < 5

    def test_load_batch_worker_crash_does_not_kill_batch(self) -> None:
        def _crash_fetch(url: str):
            if "crash" in url:
                raise RuntimeError("extractor bug")
            return MagicMock(
                is_success=True,
                content="<html><body><article><p>ok text</p></article></body></html>",
                content_type="text/html",
            )

        fetcher = MagicMock()
        fetcher.fetch.side_effect = _crash_fetch
        loader = ResourceLoader(fetcher=fetcher, max_workers=2)
        entries = [
            ("ok1", "https://example.com/ok"),
            ("bad1", "https://example.com/crash"),
        ]
        results = loader.load_batch(entries)
        assert len(results) == 2
        assert not results["bad1"].is_success
        assert "extractor bug" in (results["bad1"].error or "")


# ===========================================================================
# ResourceCache tests
# ===========================================================================


class TestResourceCache:
    def test_cache_put_and_get(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        resource = _ok("https://example.com/a", text="cached text")
        cache.put("art:1", resource)
        got = cache.get("art:1", expected_url="https://example.com/a")
        assert got is not None
        assert got.text == "cached text"
        assert got.is_success

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        assert cache.get("nonexistent", expected_url="https://x.com") is None

    def test_cache_stores_permanent_failures(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        cache.put("art:1", _fail("https://example.com"))
        cached = cache.get("art:1", expected_url="https://example.com")
        assert cached is not None
        assert cached.is_success is False
        assert cached.error == "timeout"

    def test_cache_does_not_store_ip_blocks(self, tmp_path: Path) -> None:
        """IP blocks are temporary — they must not be cached."""
        cache = ResourceCache(tmp_path)
        resource = _blocked("https://youtube.com/watch?v=abc")
        assert resource.is_blocked
        cache.put("yt:1", resource)
        assert cache.get("yt:1", expected_url="https://youtube.com/watch?v=abc") is None

    def test_cache_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        (tmp_path / "art_1.json").write_text("not valid json{{{", "utf-8")
        assert cache.get("art:1", expected_url="https://x.com") is None

    def test_cache_non_dict_json_returns_none(self, tmp_path: Path) -> None:
        """Valid JSON that is not a dict (e.g. array or string) should be a cache miss."""
        cache = ResourceCache(tmp_path)
        (tmp_path / "art_1.json").write_text('["not", "a", "dict"]', "utf-8")
        assert cache.get("art:1", expected_url="https://x.com") is None
        (tmp_path / "art_2.json").write_text('"just a string"', "utf-8")
        assert cache.get("art:2", expected_url="https://x.com") is None

    def test_cache_url_mismatch_invalidates(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        cache.put("art:1", _ok("https://old-url.com/a"))
        got = cache.get("art:1", expected_url="https://new-url.com/a")
        assert got is None

    def test_get_or_load_uses_cache(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        cache.put("a1", _ok("https://example.com/1", text="from cache"))

        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {}

        results, hits = cache.get_or_load(
            [("a1", "https://example.com/1")],
            loader,
        )
        assert hits == 1
        assert results["a1"].text == "from cache"
        loader.load_batch.assert_not_called()

    def test_get_or_load_fetches_missing(self, tmp_path: Path) -> None:
        cache = ResourceCache(tmp_path)
        cache.put("a1", _ok("https://example.com/1", text="cached"))

        fetched_resource = _ok("https://example.com/2", text="freshly loaded")
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {"a2": fetched_resource}

        results, hits = cache.get_or_load(
            [("a1", "https://example.com/1"), ("a2", "https://example.com/2")],
            loader,
        )
        assert hits == 1
        assert results["a1"].text == "cached"
        assert results["a2"].text == "freshly loaded"
        loader.load_batch.assert_called_once_with([("a2", "https://example.com/2")])

        got = cache.get("a2", expected_url="https://example.com/2")
        assert got is not None
        assert got.text == "freshly loaded"


# ===========================================================================
# load_resource_texts integration tests
# ===========================================================================


class TestLoadResourceTexts:
    def test_empty_entries(self) -> None:
        assert load_resource_texts([]) == {}

    def test_returns_title_text_map(self) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "art:1": _ok("https://example.com/1", text="Full article text " * 20),
        }
        entries = [_entry("art:1", "https://example.com/1")]
        result = load_resource_texts(entries, loader=loader)
        assert len(result) == 1
        assert "art:1" in result
        title, text = result["art:1"]
        assert title == "Title art:1"
        assert text == "Full article text " * 20

    def test_filters_short_content(self) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "a1": _ok("https://example.com/1", text="short"),
            "a2": _ok("https://example.com/2", text="x" * 500),
        }
        entries = [
            _entry("a1", "https://example.com/1"),
            _entry("a2", "https://example.com/2"),
        ]
        result = load_resource_texts(entries, loader=loader, min_resource_chars=200)
        assert len(result) == 1
        assert "a2" in result

    def test_youtube_lower_threshold(self) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "yt1": LoadedResource(
                url="https://youtube.com/watch?v=abc",
                text="x" * 120,
                content_type="youtube/transcript:en",
                is_success=True,
            ),
        }
        entries = [_entry("yt1", "https://youtube.com/watch?v=abc")]
        result = load_resource_texts(entries, loader=loader, min_resource_chars=200)
        assert len(result) == 1

    def test_custom_min_resource_chars(self) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "a1": _ok("https://example.com/1", text="x" * 50),
        }
        entries = [_entry("a1", "https://example.com/1")]
        result = load_resource_texts(entries, loader=loader, min_resource_chars=30)
        assert len(result) == 1

        result_strict = load_resource_texts(entries, loader=loader, min_resource_chars=100)
        assert len(result_strict) == 0

    def test_with_cache(self, tmp_path: Path) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "a1": _ok("https://example.com/1", text="loaded " * 100),
        }
        entries = [_entry("a1", "https://example.com/1")]
        result1 = load_resource_texts(entries, cache_dir=tmp_path, loader=loader)
        assert len(result1) == 1
        loader.load_batch.assert_called_once()

        loader.load_batch.reset_mock()
        loader.load_batch.return_value = {}
        result2 = load_resource_texts(entries, cache_dir=tmp_path, loader=loader)
        assert len(result2) == 1
        loader.load_batch.assert_not_called()


# ===========================================================================
# PipelineInput round-trip tests
# ===========================================================================


class TestPipelineInputMinResourceChars:
    def test_min_resource_chars_round_trips_through_json(self, tmp_path: Path) -> None:
        """Verify min_resource_chars serialized into pipeline_input.json is read back."""
        from news_recap.recap.storage.pipeline_io import read_pipeline_input

        payload = {
            "run_date": "2026-01-01",
            "articles": [],
            "preferences": {"max_headline_chars": 120, "language": "ru"},
            "routing_defaults": {
                "default_agent": "codex",
                "task_model_map": {},
                "command_templates": {},
                "task_type_timeout_map": {},
            },
            "agent_override": None,
            "data_dir": str(tmp_path),
            "min_resource_chars": 500,
        }
        (tmp_path / "pipeline_input.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            "utf-8",
        )
        inp = read_pipeline_input(str(tmp_path))
        assert inp.min_resource_chars == 500

    def test_min_resource_chars_defaults_when_missing(self, tmp_path: Path) -> None:
        """Legacy pipeline_input.json without min_resource_chars uses the default."""
        from news_recap.recap.storage.pipeline_io import (
            _DEFAULT_MIN_RESOURCE_CHARS,
            read_pipeline_input,
        )

        payload = {
            "run_date": "2026-01-01",
            "articles": [],
            "preferences": {"max_headline_chars": 120, "language": "ru"},
            "routing_defaults": {
                "default_agent": "codex",
                "task_model_map": {},
                "command_templates": {},
                "task_type_timeout_map": {},
            },
            "agent_override": None,
        }
        (tmp_path / "pipeline_input.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            "utf-8",
        )
        inp = read_pipeline_input(str(tmp_path))
        assert inp.min_resource_chars == _DEFAULT_MIN_RESOURCE_CHARS


# ===========================================================================
# load_cached_resource_texts tests
# ===========================================================================


class TestLoadCachedResourceTexts:
    def test_empty_entries(self, tmp_path: Path) -> None:
        assert load_cached_resource_texts([], cache_dir=tmp_path) == {}

    def test_returns_cached_entries(self, tmp_path: Path) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "a1": _ok("https://example.com/1", text="loaded " * 100),
        }
        entries = [_entry("a1", "https://example.com/1")]
        load_resource_texts(entries, cache_dir=tmp_path, loader=loader)

        result = load_cached_resource_texts(entries, cache_dir=tmp_path)
        assert len(result) == 1
        assert "a1" in result
        assert result["a1"][0] == "Title a1"

    def test_skips_uncached_entries(self, tmp_path: Path) -> None:
        entries = [_entry("missing", "https://example.com/missing")]
        result = load_cached_resource_texts(entries, cache_dir=tmp_path)
        assert len(result) == 0

    def test_respects_min_resource_chars(self, tmp_path: Path) -> None:
        loader = MagicMock(spec=ResourceLoader)
        loader.load_batch.return_value = {
            "a1": _ok("https://example.com/1", text="short"),
        }
        entries = [_entry("a1", "https://example.com/1")]
        load_resource_texts(entries, cache_dir=tmp_path, loader=loader)

        result = load_cached_resource_texts(entries, cache_dir=tmp_path, min_resource_chars=200)
        assert len(result) == 0
