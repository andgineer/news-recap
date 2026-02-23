"""Tests for the shared HTTP module components."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from news_recap.http.fetcher import HttpFetcher
from news_recap.http.html_extractor import ExtractionResult, extract_text
from news_recap.http.youtube_extractor import extract_video_id, is_youtube_url


class TestHtmlExtractor:
    def test_extract_from_simple_html(self):
        html = (
            "<html><body><p>Hello world. This is a test article with enough text.</p></body></html>"
        )
        result = extract_text(html)
        assert isinstance(result, ExtractionResult)

    def test_extract_from_empty_html(self):
        result = extract_text("")
        assert not result.is_success
        assert result.error == "empty HTML input"

    def test_extract_with_max_chars(self):
        html = "<html><body><p>" + "x" * 10000 + "</p></body></html>"
        result = extract_text(html, max_chars=100)
        if result.is_success:
            assert len(result.text) <= 100

    def test_extract_preserves_url(self):
        html = "<html><body><article><p>Content here.</p></article></body></html>"
        result = extract_text(html, url="https://example.com/article")
        assert isinstance(result, ExtractionResult)


class TestYoutubeExtractor:
    def test_extract_video_id_standard_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_short_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_not_youtube(self):
        assert extract_video_id("https://example.com/article") is None

    def test_is_youtube_url_true(self):
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_is_youtube_url_false(self):
        assert not is_youtube_url("https://example.com/page")

    def test_extract_video_id_with_extra_params(self):
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120") == "dQw4w9WgXcQ"
        )

    def test_extract_video_id_empty_string(self):
        assert extract_video_id("") is None


class TestHttpFetcher:
    @patch("news_recap.http.fetcher.httpx.Client")
    def test_fetch_success(self, mock_client_cls: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>OK</body></html>"
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.is_success = True
        mock_client_cls.return_value.get.return_value = mock_resp

        fetcher = HttpFetcher()
        result = fetcher.fetch("https://example.com")
        assert result.is_success
        assert result.status_code == 200
        assert "OK" in result.content

    @patch("news_recap.http.fetcher.httpx.Client")
    def test_fetch_timeout(self, mock_client_cls: MagicMock) -> None:
        mock_client_cls.return_value.get.side_effect = httpx.TimeoutException("timed out")

        fetcher = HttpFetcher()
        result = fetcher.fetch("https://example.com/slow")
        assert not result.is_success
        assert result.error == "timeout"

    @patch("news_recap.http.fetcher.httpx.Client")
    def test_fetch_http_error(self, mock_client_cls: MagicMock) -> None:
        mock_client_cls.return_value.get.side_effect = httpx.HTTPError("connection reset")

        fetcher = HttpFetcher()
        result = fetcher.fetch("https://example.com/broken")
        assert not result.is_success
        assert "connection reset" in (result.error or "")

    @patch("news_recap.http.fetcher.httpx.Client")
    def test_fetch_non_success_status(self, mock_client_cls: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.is_success = False
        mock_client_cls.return_value.get.return_value = mock_resp

        fetcher = HttpFetcher()
        result = fetcher.fetch("https://example.com/forbidden")
        assert not result.is_success
        assert result.status_code == 403
        assert result.error == "HTTP 403"
