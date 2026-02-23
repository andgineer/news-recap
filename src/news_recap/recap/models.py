"""Domain models shared by recap pipeline stages."""

from __future__ import annotations

from typing import Any

import msgspec

from news_recap.recap.contracts import ArticleIndexEntry

_DEFAULT_NOT_INTERESTING = "horoscopes, medical advice, sports (except Russia), Epstein files"
_DEFAULT_INTERESTING = "Russia, Serbia, war in Ukraine"


class UserPreferences(msgspec.Struct):
    """User preferences for digest composition."""

    max_headline_chars: int = 120
    interesting: str = _DEFAULT_INTERESTING
    not_interesting: str = _DEFAULT_NOT_INTERESTING
    language: str = "ru"

    def format_for_prompt(self) -> str:
        parts: list[str] = []
        if self.not_interesting:
            parts.append(f"DISCARD these topics (always trash): {self.not_interesting}")
        if self.interesting:
            parts.append(
                f"PRIORITY topics (user wants extra detail): {self.interesting}",
            )
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
    resource_text: str | None = None


class DigestEvent(msgspec.Struct):
    """Grouped event with denormalized articles."""

    event_id: str
    title: str
    significance: str
    articles: list[DigestArticle]
    narrative: str | None = None


class DigestBlock(msgspec.Struct):
    """Composed digest block."""

    theme: str
    headline: str
    body: str
    sources: list[dict[str, str]]


class Digest(msgspec.Struct):
    """Top-level digest state — the single checkpoint object for the recap pipeline."""

    digest_id: str
    business_date: str
    status: str
    pipeline_dir: str
    articles: list[DigestArticle]
    events: list[DigestEvent] = []
    blocks: list[DigestBlock] = []
    completed_phases: list[str] = []
