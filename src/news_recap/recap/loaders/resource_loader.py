"""Resource loader for recap pipeline — wraps shared HTTP module."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

from news_recap.http.fetcher import HttpFetcher
from news_recap.http.html_extractor import extract_text
from news_recap.http.youtube_extractor import IP_BLOCKED_ERROR, fetch_transcript, is_youtube_url

logger = logging.getLogger(__name__)

_YT_DELAY_SECONDS = 3.0
_MIN_YT_SECONDS = 45.0


@dataclass(slots=True)
class LoadedResource:
    """Result of loading and extracting content from a URL."""

    url: str
    text: str
    content_type: str
    is_success: bool
    error: str | None = None

    @property
    def is_blocked(self) -> bool:
        """True when the failure was caused by an IP/bot block or early-stop (temporary)."""
        return self.error in (IP_BLOCKED_ERROR, "not_attempted")


class ResourceLoader:
    """Load and extract text content from article URLs.

    YouTube and HTML are processed on separate paths:

    * **HTML** — concurrent via ``ThreadPoolExecutor`` with per-domain
      semaphores (``max_per_domain`` concurrent requests per host).
    * **YouTube** — sequential in a dedicated thread with a configurable
      delay between requests.  The YouTube thread runs for at least
      ``min_yt_seconds`` before being stopped; if HTML finishes faster
      the loader waits for the remainder so short batches don't cut
      YouTube loading short.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        fetcher: HttpFetcher | None = None,
        max_chars: int = 50_000,
        max_workers: int = 10,
        max_per_domain: int = 3,
        yt_delay: float = _YT_DELAY_SECONDS,
        min_yt_seconds: float = _MIN_YT_SECONDS,
    ) -> None:
        self._fetcher = fetcher or HttpFetcher()
        self._owns_fetcher = fetcher is None
        self._max_chars = max_chars
        self._max_workers = max_workers
        self._max_per_domain = max_per_domain
        self._yt_delay = yt_delay
        self._min_yt_seconds = min_yt_seconds
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
        Returns a dict keyed by ``source_id``.  YouTube entries that
        were not reached before HTML finished are simply omitted from the
        result (not marked as failures).
        """
        if not entries:
            return {}

        html_entries = []
        yt_entries = []
        for sid, url in entries:
            if is_youtube_url(url):
                yt_entries.append((sid, url))
            else:
                html_entries.append((sid, url))

        results: dict[str, LoadedResource] = {}
        yt_results: dict[str, LoadedResource] = {}
        stop = threading.Event()

        yt_thread = None
        if yt_entries:
            yt_thread = threading.Thread(
                target=self._load_youtube_batch,
                args=(yt_entries, yt_results, stop),
                daemon=True,
            )
            yt_thread.start()

        html_start = time.monotonic()
        if html_entries:
            self._load_html_batch(html_entries, results)
        html_elapsed = time.monotonic() - html_start

        if yt_thread is not None:
            remaining = self._min_yt_seconds - html_elapsed
            if remaining > 0:
                logger.info(
                    "HTML finished in %.1fs (< %.0fs min); waiting %.1fs more for YouTube",
                    html_elapsed,
                    self._min_yt_seconds,
                    remaining,
                )
                stop.wait(timeout=remaining)
            stop.set()
            yt_thread.join(timeout=5.0)
            results.update(yt_results)

        return results

    # ------------------------------------------------------------------
    # HTML: concurrent with per-domain semaphores
    # ------------------------------------------------------------------

    def _load_html_batch(
        self,
        entries: list[tuple[str, str]],
        results: dict[str, LoadedResource],
    ) -> None:
        for _, url in entries:
            domain = urlparse(url).netloc.lower()
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = threading.Semaphore(self._max_per_domain)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_to_sid = {
                pool.submit(self._safe_load_html, sid, url): sid for sid, url in entries
            }
            for future in as_completed(future_to_sid):
                sid = future_to_sid[future]
                results[sid] = future.result()

    def _safe_load_html(self, source_id: str, url: str) -> LoadedResource:
        domain = urlparse(url).netloc.lower()
        with self._sem_lock:
            sem = self._domain_semaphores.setdefault(
                domain,
                threading.Semaphore(self._max_per_domain),
            )
        try:
            with sem:
                return self._load_html(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error loading %s (%s): %s", source_id, url, exc)
            return LoadedResource(
                url=url,
                text="",
                content_type="",
                is_success=False,
                error=f"unexpected: {exc}",
            )

    # ------------------------------------------------------------------
    # YouTube: sequential in a dedicated thread, stops when signalled
    # ------------------------------------------------------------------

    def _load_youtube_batch(
        self,
        entries: list[tuple[str, str]],
        results: dict[str, LoadedResource],
        stop: threading.Event,
    ) -> None:
        total = len(entries)
        ok = 0
        for i, (sid, url) in enumerate(entries):
            if stop.is_set():
                skipped = entries[i:]
                logger.info(
                    "YouTube: stopping after %d/%d (HTML finished, %d transcripts loaded,"
                    " %d not attempted)",
                    i,
                    total,
                    ok,
                    len(skipped),
                )
                for skip_sid, skip_url in skipped:
                    results[skip_sid] = LoadedResource(
                        url=skip_url,
                        text="",
                        content_type="youtube/transcript",
                        is_success=False,
                        error="not_attempted",
                    )
                return

            try:
                res = self._load_youtube(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected error loading YouTube %s: %s", sid, exc)
                res = LoadedResource(
                    url=url,
                    text="",
                    content_type="youtube/transcript",
                    is_success=False,
                    error=f"unexpected: {exc}",
                )
            results[sid] = res

            if res.is_blocked:
                skipped = total - i - 1
                logger.warning(
                    "YouTube IP blocked after %d/%d videos — aborting remaining %d",
                    i + 1,
                    total,
                    skipped,
                )
                return

            if res.is_success:
                ok += 1
            if (i + 1) % 10 == 0 or (i + 1) == total:
                logger.info("YouTube: %d/%d processed (%d transcripts)", i + 1, total, ok)

            if i < total - 1 and stop.wait(timeout=self._yt_delay):
                skipped = entries[i + 1 :]
                logger.info(
                    "YouTube: stopping after %d/%d (HTML finished, %d transcripts loaded,"
                    " %d not attempted)",
                    i + 1,
                    total,
                    ok,
                    len(skipped),
                )
                for skip_sid, skip_url in skipped:
                    results[skip_sid] = LoadedResource(
                        url=skip_url,
                        text="",
                        content_type="youtube/transcript",
                        is_success=False,
                        error="not_attempted",
                    )
                return

        logger.info("YouTube done: %d/%d transcripts loaded", ok, total)

    # ------------------------------------------------------------------
    # Single-URL loaders
    # ------------------------------------------------------------------

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
