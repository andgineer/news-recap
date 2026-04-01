"""Domain models shared by recap pipeline stages."""

from __future__ import annotations

from typing import Any

import langcodes
import msgspec

from news_recap.recap.contracts import ArticleIndexEntry


def language_display_name(code: str) -> str:
    """Return the English display name for a BCP-47 language code.

    Falls back to the code itself for unknown codes.

    >>> language_display_name("ru")
    'Russian'
    >>> language_display_name("en")
    'English'
    >>> language_display_name("xx")
    'xx'
    """
    tag = langcodes.get(code)
    return tag.display_name() if tag.is_valid() else code


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
    alt_urls: list[dict[str, str]] = []


class DigestBlock(msgspec.Struct):
    """A thematic block in the final digest.

    ``title`` is a short topic label and ``summary`` holds the 2-4 sentence prose.
    ``article_ids`` references the source articles that belong to this block.
    """

    title: str
    article_ids: list[str]
    summary: str = ""


class DigestSection(msgspec.Struct):
    """A reader-facing section (recap) grouping related blocks.

    ``block_indices`` are indices into ``Digest.blocks``.
    ``summary`` is a 1-2 sentence overview of the section topic.
    """

    title: str
    block_indices: list[int]
    summary: str = ""


class Digest(msgspec.Struct):
    """Top-level digest state — the single checkpoint object for the recap pipeline."""

    digest_id: str
    run_date: str
    status: str
    pipeline_dir: str
    articles: list[DigestArticle]
    blocks: list[DigestBlock] = []
    completed_phases: list[str] = []
    recaps: list[DigestSection] = []
    day_summary: str = ""
