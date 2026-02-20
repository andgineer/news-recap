"""Async-capable HTTP client with retries and timeout."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsRecapBot/1.0; +https://github.com/andgineer/news-recap)"
)


@dataclass(slots=True)
class FetchResult:
    """Result of an HTTP fetch operation."""

    url: str
    status_code: int
    content: str
    content_type: str
    is_success: bool
    error: str | None = None


class HttpFetcher:
    """HTTP client wrapper with retry, timeout, and user-agent configuration."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._max_retries = max_retries
        base_headers = {"User-Agent": user_agent}
        if headers:
            base_headers.update(headers)
        transport = httpx.HTTPTransport(retries=max_retries)
        self._client = httpx.Client(
            timeout=self._timeout,
            headers=base_headers,
            transport=transport,
            follow_redirects=True,
        )

    def fetch(self, url: str) -> FetchResult:
        """Fetch URL content, returning structured result."""

        try:
            response = self._client.get(url)
            content_type = response.headers.get("content-type", "")
            return FetchResult(
                url=url,
                status_code=response.status_code,
                content=response.text,
                content_type=content_type,
                is_success=response.is_success,
                error=None if response.is_success else f"HTTP {response.status_code}",
            )
        except httpx.TimeoutException:
            logger.warning("Timeout fetching %s", url)
            return FetchResult(
                url=url,
                status_code=0,
                content="",
                content_type="",
                is_success=False,
                error="timeout",
            )
        except httpx.HTTPError as exc:
            logger.warning("HTTP error fetching %s: %s", url, exc)
            return FetchResult(
                url=url,
                status_code=0,
                content="",
                content_type="",
                is_success=False,
                error=str(exc),
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpFetcher:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
