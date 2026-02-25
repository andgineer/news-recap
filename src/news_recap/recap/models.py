"""Domain models shared by recap pipeline stages."""

from __future__ import annotations

from typing import Any

import msgspec

from news_recap.recap.contracts import ArticleIndexEntry

_DEFAULT_EXCLUDE = "horoscopes, medical advice, sports (except Russia), Epstein files"
_DEFAULT_FOLLOW = "Russia, Serbia, war in Ukraine"


class UserPreferences(msgspec.Struct):
    """User preferences for digest composition."""

    max_headline_chars: int = 120
    follow: str = _DEFAULT_FOLLOW
    exclude: str = _DEFAULT_EXCLUDE
    language: str = "ru"

    def format_for_prompt(self) -> str:
        parts: list[str] = []
        if self.exclude:
            parts.append(f"EXCLUDE: {self.exclude}")
        if self.follow:
            parts.append(f"FOLLOW: {self.follow}")
        return "\n".join(parts) if parts else "no specific preferences"

    def to_dict(self) -> dict[str, object]:
        return msgspec.structs.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPreferences:
        return msgspec.convert(data, UserPreferences)


def to_article_index(entries: list[DigestArticle]) -> list[ArticleIndexEntry]:
    """Convert digest articles to the lighter article index entries."""
    return [
        ArticleIndexEntry(
            source_id=e.article_id,
            title=e.title,
            url=e.url,
            source=e.source,
            published_at=e.published_at,
        )
        for e in entries
    ]


class DigestArticle(msgspec.Struct):
    """Article within a digest — carries pipeline state."""

    article_id: str
    title: str
    url: str
    source: str
    published_at: str
    clean_text: str
    verdict: str | None = None
    enriched_title: str | None = None
    enriched_text: str | None = None
    resource_loaded: bool = False


class DigestBlock(msgspec.Struct):
    """A thematic block in the final digest.

    ``title`` is a 2-4 sentence summary produced by MAP/REDUCE.
    ``article_ids`` references the source articles that belong to this block.
    """

    title: str
    article_ids: list[str]


class Digest(msgspec.Struct):
    """Top-level digest state — the single checkpoint object for the recap pipeline."""

    digest_id: str
    business_date: str
    status: str
    pipeline_dir: str
    articles: list[DigestArticle]
    blocks: list[DigestBlock] = []
    completed_phases: list[str] = []
