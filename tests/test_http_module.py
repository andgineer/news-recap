"""Tests for the shared HTTP module components."""

from __future__ import annotations

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
