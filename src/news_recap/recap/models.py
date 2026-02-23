"""Domain models shared by recap pipeline stages."""

from __future__ import annotations

import msgspec


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
