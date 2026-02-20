"""HTML to clean text extraction using trafilatura."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import trafilatura

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionResult:
    """Result of HTML text extraction."""

    text: str
    is_success: bool
    error: str | None = None


def extract_text(
    html: str,
    *,
    url: str | None = None,
    include_tables: bool = True,
    include_links: bool = False,
    max_chars: int = 0,
) -> ExtractionResult:
    """Extract main content text from HTML using trafilatura.

    Falls back to a simpler extraction if main extraction fails.
    """

    if not html or not html.strip():
        return ExtractionResult(text="", is_success=False, error="empty HTML input")

    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_tables=include_tables,
            include_links=include_links,
            favor_precision=True,
            deduplicate=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("trafilatura.extract failed for %s: %s", url or "<unknown>", exc)
        text = None

    if not text:
        try:
            text = trafilatura.extract(
                html,
                url=url,
                include_tables=include_tables,
                include_links=include_links,
                favor_recall=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("trafilatura fallback failed for %s: %s", url or "<unknown>", exc)
            return ExtractionResult(
                text="",
                is_success=False,
                error=f"extraction failed: {exc}",
            )

    if not text:
        return ExtractionResult(text="", is_success=False, error="no content extracted")

    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()

    return ExtractionResult(text=text, is_success=True)
