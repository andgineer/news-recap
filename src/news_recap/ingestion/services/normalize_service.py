"""Normalization service for source articles."""

from __future__ import annotations

from datetime import UTC

from news_recap.config import IngestionSettings
from news_recap.ingestion.cleaning import (
    canonicalize_url,
    clean_article_text,
    extract_domain,
    url_hash,
)
from news_recap.ingestion.language import detect_language
from news_recap.ingestion.models import NormalizedArticle, SourceArticle


class ArticleNormalizationService:
    """Converts source payloads into normalized article records."""

    def __init__(self, *, source_name: str, ingestion_settings: IngestionSettings) -> None:
        self.source_name = source_name
        self.ingestion_settings = ingestion_settings

    def normalize(self, source_article: SourceArticle) -> NormalizedArticle:
        cleaned = clean_article_text(
            content_html=source_article.content,
            summary_html=source_article.summary,
            max_chars=self.ingestion_settings.clean_text_max_chars,
        )
        canonical_url = canonicalize_url(source_article.url)

        return NormalizedArticle(
            source_name=self.source_name,
            external_id=source_article.external_id,
            url=source_article.url,
            url_canonical=canonical_url,
            url_hash=url_hash(canonical_url),
            title=source_article.title,
            source_domain=extract_domain(canonical_url),
            published_at=source_article.published_at.astimezone(UTC),
            language_detected=detect_language(cleaned.text, source_article.title),
            content_raw=source_article.content,
            summary_raw=source_article.summary,
            is_full_content=cleaned.is_full_content,
            needs_enrichment=cleaned.needs_enrichment,
            clean_text=cleaned.text,
            clean_text_chars=len(cleaned.text),
            is_truncated=cleaned.is_truncated,
        )
