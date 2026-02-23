"""Resource loader for recap pipeline — wraps shared HTTP module."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

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
        max_workers: int = 10,
        max_per_domain: int = 3,
    ) -> None:
        self._fetcher = fetcher or HttpFetcher()
        self._owns_fetcher = fetcher is None
        self._max_chars = max_chars
        self._max_workers = max_workers
        self._max_per_domain = max_per_domain
        self._domain_semaphores: dict[str, threading.Semaphore] = {}
        self._sem_lock = threading.Lock()

    def load(self, url: str) -> LoadedResource:
        """Load content from a URL, auto-detecting YouTube vs HTML."""
        if is_youtube_url(url):
            return self._load_youtube(url)
        return self._load_html(url)

    def load_batch(
        self,
        entries: list[tuple[str, str]],
    ) -> dict[str, LoadedResource]:
        """Fetch multiple URLs concurrently with per-domain rate limiting.

        *entries* is a list of ``(source_id, url)`` pairs.
        Returns a dict keyed by ``source_id`` — always contains one entry
        per input, even on failure.
        """
        if not entries:
            return {}

        for _, url in entries:
            domain = urlparse(url).netloc.lower()
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = threading.Semaphore(self._max_per_domain)

        results: dict[str, LoadedResource] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_to_sid = {pool.submit(self._safe_load, sid, url): sid for sid, url in entries}
            for future in as_completed(future_to_sid):
                sid = future_to_sid[future]
                results[sid] = future.result()

        return results

    def _safe_load(self, source_id: str, url: str) -> LoadedResource:
        """Load a single URL with domain semaphore and crash isolation."""
        domain = urlparse(url).netloc.lower()
        with self._sem_lock:
            sem = self._domain_semaphores.setdefault(
                domain,
                threading.Semaphore(self._max_per_domain),
            )
        try:
            with sem:
                return self.load(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error loading %s (%s): %s", source_id, url, exc)
            return LoadedResource(
                url=url,
                text="",
                content_type="",
                is_success=False,
                error=f"unexpected: {exc}",
            )

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
