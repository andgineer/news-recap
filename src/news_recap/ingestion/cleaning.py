"""HTML to text cleaning and normalization utilities."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class CleanedText:
    """Output of HTML to text cleaning."""

    text: str
    is_truncated: bool
    is_full_content: bool
    needs_enrichment: bool


def clean_article_text(
    *,
    content_html: str | None,
    summary_html: str | None,
    max_chars: int,
    full_content_min_chars: int = 700,
) -> CleanedText:
    """Clean HTML payload and infer whether full content is available."""

    content_text = html_to_text(content_html or "")
    summary_text = html_to_text(summary_html or "")

    chosen = content_text or summary_text
    is_full_content = bool(content_text and len(content_text) >= full_content_min_chars)
    if not is_full_content and content_text and summary_text:
        is_full_content = len(content_text) >= len(summary_text) + 200

    truncated = False
    if len(chosen) > max_chars:
        chosen = chosen[:max_chars].rstrip()
        truncated = True

    return CleanedText(
        text=chosen,
        is_truncated=truncated,
        is_full_content=is_full_content,
        needs_enrichment=not is_full_content,
    )


def html_to_text(raw_html: str) -> str:
    """Convert HTML markup into normalized plain text."""

    if not raw_html:
        return ""
    no_scripts = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    stripped = _TAG_RE.sub(" ", no_scripts)
    unescaped = html.unescape(stripped)
    normalized = _WHITESPACE_RE.sub(" ", unescaped)
    return normalized.strip()


def canonicalize_url(url: str) -> str:
    """Normalize URL for idempotent hashing and uniqueness checks."""

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    path = parsed.path or "/"
    normalized_path = re.sub(r"/{2,}", "/", path)
    normalized_query = "&".join(
        sorted(filter(None, parsed.query.split("&"))),
    )
    cleaned = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        path=normalized_path,
        params="",
        query=normalized_query,
        fragment="",
    )
    return str(urlunparse(cleaned))


def url_hash(url: str) -> str:
    """Stable hash of canonical URL."""

    canonical = canonicalize_url(url)
    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324


def extract_domain(url: str) -> str:
    """Get normalized domain from URL."""

    return urlparse(url).netloc.lower() or "unknown"
