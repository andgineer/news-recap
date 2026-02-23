"""Resource loader for recap pipeline — wraps shared HTTP module."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from news_recap.http.fetcher import HttpFetcher
from news_recap.http.html_extractor import extract_text
from news_recap.http.youtube_extractor import fetch_transcript, is_youtube_url

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LoadedResource:
    """Result of loading and extracting content from a URL."""

    url: str
    text: str
    content_type: str
    is_success: bool
    error: str | None = None


class ResourceLoader:
    """Load and extract text content from article URLs.

    Handles both regular web pages (via HTML extraction) and YouTube videos
    (via subtitle/transcript extraction). Uses the shared http module.
    """

    def __init__(
        self,
        *,
        fetcher: HttpFetcher | None = None,
        max_chars: int = 50_000,
    ) -> None:
        self._fetcher = fetcher or HttpFetcher()
        self._owns_fetcher = fetcher is None
        self._max_chars = max_chars

    def load(self, url: str) -> LoadedResource:
        """Load content from a URL, auto-detecting YouTube vs HTML."""

        if is_youtube_url(url):
            return self._load_youtube(url)
        return self._load_html(url)

    def _load_youtube(self, url: str) -> LoadedResource:
        result = fetch_transcript(url, max_chars=self._max_chars)
        if result.is_success:
            return LoadedResource(
                url=url,
                text=result.text,
                content_type=f"youtube/transcript:{result.language}",
                is_success=True,
            )
        return LoadedResource(
            url=url,
            text="",
            content_type="youtube/transcript",
            is_success=False,
            error=result.error,
        )

    def _load_html(self, url: str) -> LoadedResource:
        fetch_result = self._fetcher.fetch(url)
        if not fetch_result.is_success:
            return LoadedResource(
                url=url,
                text="",
                content_type=fetch_result.content_type,
                is_success=False,
                error=fetch_result.error,
            )

        extraction = extract_text(
            fetch_result.content,
            url=url,
            max_chars=self._max_chars,
        )
        if extraction.is_success:
            return LoadedResource(
                url=url,
                text=extraction.text,
                content_type=fetch_result.content_type,
                is_success=True,
            )
        return LoadedResource(
            url=url,
            text="",
            content_type=fetch_result.content_type,
            is_success=False,
            error=extraction.error,
        )

    def close(self) -> None:
        if self._owns_fetcher:
            self._fetcher.close()

    def __enter__(self) -> ResourceLoader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
