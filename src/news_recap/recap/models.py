"""Domain models shared by recap pipeline and ingestion repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SourceCorpusEntry:
    """User-scoped source entry resolved from shared articles via user link."""

    source_id: str
    article_id: str
    title: str
    url: str
    source: str
    published_at: datetime
    clean_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "article_id": self.article_id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at.isoformat(),
            "clean_text": self.clean_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceCorpusEntry:
        return cls(
            source_id=str(data["source_id"]),
            article_id=str(data["article_id"]),
            title=str(data["title"]),
            url=str(data["url"]),
            source=str(data["source"]),
            published_at=datetime.fromisoformat(str(data["published_at"])),
            clean_text=str(data.get("clean_text", "")),
        )
