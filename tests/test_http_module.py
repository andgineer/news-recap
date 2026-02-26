"""Tests for the shared HTTP module components."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from news_recap.http.fetcher import HttpFetcher
from news_recap.http.html_extractor import ExtractionResult, extract_text
from news_recap.http.youtube_extractor import (
    AGE_RESTRICTED_ERROR,
    IP_BLOCKED_ERROR,
    SUBTITLES_DISABLED_ERROR,
    TRANSCRIPT_RETRIEVAL_FAILED_ERROR,
    VIDEO_UNAVAILABLE_ERROR,
    extract_video_id,
    fetch_transcript,
    is_youtube_url,
)


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


# ---------------------------------------------------------------------------
# YouTube transcript error classification
# ---------------------------------------------------------------------------

_YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
_VIDEO_ID = "dQw4w9WgXcQ"


class TestFetchTranscriptErrorMapping:
    """Verify that specific youtube-transcript-api exceptions map to stable error codes."""

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_transcripts_disabled_returns_subtitles_disabled(self, mock_api_cls: MagicMock) -> None:
        from youtube_transcript_api._errors import TranscriptsDisabled

        mock_api_cls.return_value.fetch.side_effect = TranscriptsDisabled(_VIDEO_ID)
        result = fetch_transcript(_YT_URL)
        assert not result.is_success
        assert result.error == SUBTITLES_DISABLED_ERROR
        assert not result.is_blocked

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_video_unavailable_returns_video_unavailable(self, mock_api_cls: MagicMock) -> None:
        from youtube_transcript_api._errors import VideoUnavailable

        mock_api_cls.return_value.fetch.side_effect = VideoUnavailable(_VIDEO_ID)
        result = fetch_transcript(_YT_URL)
        assert not result.is_success
        assert result.error == VIDEO_UNAVAILABLE_ERROR

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_video_unplayable_returns_video_unavailable(self, mock_api_cls: MagicMock) -> None:
        from youtube_transcript_api._errors import VideoUnplayable

        mock_api_cls.return_value.fetch.side_effect = VideoUnplayable(
            _VIDEO_ID, reason="private", sub_reasons=[]
        )
        result = fetch_transcript(_YT_URL)
        assert not result.is_success
        assert result.error == VIDEO_UNAVAILABLE_ERROR

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_age_restricted_returns_age_restricted(self, mock_api_cls: MagicMock) -> None:
        from youtube_transcript_api._errors import AgeRestricted

        mock_api_cls.return_value.fetch.side_effect = AgeRestricted(_VIDEO_ID)
        result = fetch_transcript(_YT_URL)
        assert not result.is_success
        assert result.error == AGE_RESTRICTED_ERROR

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_request_blocked_returns_ip_blocked(self, mock_api_cls: MagicMock) -> None:
        from youtube_transcript_api._errors import RequestBlocked

        mock_api_cls.return_value.fetch.side_effect = RequestBlocked(_VIDEO_ID)
        result = fetch_transcript(_YT_URL)
        assert not result.is_success
        assert result.error == IP_BLOCKED_ERROR
        assert result.is_blocked

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_unknown_error_falls_back_to_retrieval_failed(self, mock_api_cls: MagicMock) -> None:
        mock_api = mock_api_cls.return_value
        mock_api.fetch.side_effect = RuntimeError("network flake")
        mock_api.list.side_effect = RuntimeError("still broken")
        result = fetch_transcript(_YT_URL)
        assert not result.is_success
        assert result.error == TRANSCRIPT_RETRIEVAL_FAILED_ERROR

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_no_transcript_found_triggers_fallback(self, mock_api_cls: MagicMock) -> None:
        """NoTranscriptFound from fetch() should fall through to _fetch_any."""
        from youtube_transcript_api._errors import NoTranscriptFound

        mock_api = mock_api_cls.return_value
        mock_api.fetch.side_effect = NoTranscriptFound(
            _VIDEO_ID,
            requested_language_codes=["ru", "en"],
            transcript_data=MagicMock(__str__=lambda self: ""),
        )
        mock_transcript = MagicMock()
        mock_transcript.language_code = "fr"
        mock_snippet = MagicMock()
        mock_snippet.text = "Bonjour"
        mock_transcript.fetch.return_value = [mock_snippet]
        mock_api.list.return_value = [mock_transcript]

        result = fetch_transcript(_YT_URL)
        assert result.is_success
        assert result.language == "fr"
        assert "Bonjour" in result.text


class TestFetchTranscriptLogLevels:
    """Permanent failures log at DEBUG, actionable failures at WARNING."""

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_subtitles_disabled_logs_debug_not_warning(
        self, mock_api_cls: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        from youtube_transcript_api._errors import TranscriptsDisabled

        mock_api_cls.return_value.fetch.side_effect = TranscriptsDisabled(_VIDEO_ID)
        with caplog.at_level("DEBUG", logger="news_recap.http.youtube_extractor"):
            fetch_transcript(_YT_URL)

        debug_msgs = [r for r in caplog.records if r.levelname == "DEBUG"]
        warning_msgs = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("subtitles_disabled" in r.message for r in debug_msgs)
        assert not any("subtitles_disabled" in r.message for r in warning_msgs)

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_unknown_error_logs_warning(
        self, mock_api_cls: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_api = mock_api_cls.return_value
        mock_api.fetch.side_effect = RuntimeError("boom")
        mock_api.list.side_effect = RuntimeError("still boom")
        with caplog.at_level("DEBUG", logger="news_recap.http.youtube_extractor"):
            fetch_transcript(_YT_URL)

        warning_msgs = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("RuntimeError" in r.message for r in warning_msgs)

    @patch("news_recap.http.youtube_extractor.YouTubeTranscriptApi")
    def test_ip_blocked_logs_warning(
        self, mock_api_cls: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        from youtube_transcript_api._errors import RequestBlocked

        mock_api_cls.return_value.fetch.side_effect = RequestBlocked(_VIDEO_ID)
        with caplog.at_level("DEBUG", logger="news_recap.http.youtube_extractor"):
            fetch_transcript(_YT_URL)

        warning_msgs = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("blocked" in r.message.lower() for r in warning_msgs)
