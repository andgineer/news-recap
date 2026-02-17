"""Common source adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from news_recap.ingestion.models import SourcePage


@dataclass(slots=True)
class SourceError(Exception):
    """Base source fetch error."""

    message: str
    code: str = "source_error"

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class TemporarySourceError(SourceError):
    """Retryable source error with cursor context."""

    from_cursor: str | None = None
    to_cursor: str | None = None
    retry_after: int | None = None


@dataclass(slots=True)
class NonRetryableSourceError(SourceError):
    """Non-retryable source error that should fail the run."""

    from_cursor: str | None = None
    to_cursor: str | None = None


class SourceAdapter(Protocol):
    """Interface for article sources."""

    name: str

    def fetch_page(self, cursor: str | None, limit: int) -> SourcePage:
        """Fetch one page from the source by cursor."""
        raise NotImplementedError


@runtime_checkable
class RunLifecycleSourceAdapter(Protocol):
    """Optional run lifecycle hook for stateful source adapters."""

    def begin_run(self) -> None:
        """Reset any source state that must not leak between runs."""
        raise NotImplementedError


@runtime_checkable
class PageCheckpointSourceAdapter(Protocol):
    """Optional hook to persist page-level progress after successful processing."""

    def mark_page_processed(self, *, next_cursor: str | None) -> None:
        """Persist progress cursor after one page is fully processed."""
        raise NotImplementedError
