from __future__ import annotations

from datetime import UTC, datetime, timezone

import allure

from news_recap.config import IngestionSettings
from news_recap.ingestion.models import SourceArticle
from news_recap.ingestion.services.normalize_service import ArticleNormalizationService

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Article Normalization"),
]

_SETTINGS = IngestionSettings()
_SOURCE = "test-feed"
_PUBLISHED = datetime(
    2026, 2, 19, 10, 0, 0, tzinfo=timezone(offset=__import__("datetime").timedelta(hours=3))
)


def _make_article(**overrides) -> SourceArticle:
    defaults = {
        "external_id": "ext-1",
        "url": "https://example.com/article-1",
        "title": "Test Article",
        "source": _SOURCE,
        "published_at": _PUBLISHED,
        "content": "<p>Full article body here.</p>",
        "summary": "<p>Short summary.</p>",
    }
    defaults.update(overrides)
    return SourceArticle(**defaults)


def _normalize(article: SourceArticle | None = None) -> ...:
    svc = ArticleNormalizationService(source_name=_SOURCE, ingestion_settings=_SETTINGS)
    return svc.normalize(article or _make_article())


def test_basic_fields_populated() -> None:
    result = _normalize()
    assert result.source_name == _SOURCE
    assert result.external_id == "ext-1"
    assert result.title == "Test Article"
    assert result.url == "https://example.com/article-1"


def test_url_canonicalized_and_hashed() -> None:
    article = _make_article(url="HTTPS://Example.Com:443/article?b=2&a=1#frag")
    result = _normalize(article)
    assert result.url_canonical == "https://example.com/article?a=1&b=2"
    assert result.url_hash  # non-empty hash string


def test_source_domain_extracted() -> None:
    result = _normalize()
    assert result.source_domain == "example.com"


def test_published_at_converted_to_utc() -> None:
    result = _normalize()
    assert result.published_at.tzinfo == UTC
    assert result.published_at == datetime(2026, 2, 19, 7, 0, 0, tzinfo=UTC)


def test_html_cleaned_from_content() -> None:
    article = _make_article(content="<p>Hello <b>world</b></p>", summary=None)
    result = _normalize(article)
    assert "<p>" not in result.clean_text
    assert "Hello world" in result.clean_text


def test_full_content_flag_when_content_long_enough() -> None:
    long_body = "<p>" + "This is a sentence with enough words. " * 30 + "</p>"
    article = _make_article(content=long_body, summary="<p>Summary.</p>")
    result = _normalize(article)
    assert result.is_full_content is True
    assert result.needs_enrichment is False


def test_short_content_marks_needs_enrichment() -> None:
    article = _make_article(content="<p>Short body.</p>", summary="<p>Summary.</p>")
    result = _normalize(article)
    assert result.is_full_content is False
    assert result.needs_enrichment is True


def test_summary_only_marks_needs_enrichment() -> None:
    article = _make_article(content=None, summary="<p>Only a summary.</p>")
    result = _normalize(article)
    assert result.is_full_content is False
    assert result.needs_enrichment is True


def test_clean_text_chars_matches_length() -> None:
    result = _normalize()
    assert result.clean_text_chars == len(result.clean_text)


def test_truncation_on_long_content() -> None:
    long_body = "<p>" + "word " * 5000 + "</p>"
    settings = IngestionSettings(clean_text_max_chars=100)
    svc = ArticleNormalizationService(source_name=_SOURCE, ingestion_settings=settings)
    result = svc.normalize(_make_article(content=long_body))
    assert result.clean_text_chars <= 100
    assert result.is_truncated is True


def test_language_detected() -> None:
    article = _make_article(
        title="Breaking news from Moscow",
        content="<p>This is a long English article about events in the capital.</p>",
    )
    result = _normalize(article)
    assert result.language_detected  # non-empty string


def test_empty_content_and_summary() -> None:
    article = _make_article(content=None, summary=None)
    result = _normalize(article)
    assert result.clean_text == ""
    assert result.clean_text_chars == 0
    assert result.is_full_content is False
