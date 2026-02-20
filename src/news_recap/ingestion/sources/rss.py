"""Generic RSS/Atom source adapter."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from defusedxml import ElementTree

from news_recap.ingestion.models import SourceArticle, SourcePage
from news_recap.ingestion.sources.base import (
    NonRetryableSourceError,
    PageCheckpointSourceAdapter,
    TemporarySourceError,
)

UNKNOWN_PUBLISHED_AT = datetime(1970, 1, 1, tzinfo=UTC)
HTTP_NOT_MODIFIED = 304
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
INOREADER_HOST_SUFFIX = "inoreader.com"
INOREADER_STREAM_PATH_PART = "/stream/"
logger = logging.getLogger(__name__)


@runtime_checkable
class RssFeedStateStore(Protocol):
    """Persistence contract for HTTP cache validators per feed URL."""

    def get_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
    ) -> tuple[str | None, str | None]:
        """Return persisted (etag, last_modified) validators for a feed."""
        raise NotImplementedError

    def upsert_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        """Persist latest (etag, last_modified) validators for a feed."""
        raise NotImplementedError


@runtime_checkable
class RssProcessingSnapshotStore(Protocol):
    """Persistence contract for crash-safe RSS processing snapshots."""

    def get_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> tuple[str, str | None, datetime] | None:
        """Return (snapshot_json, next_cursor, updated_at) if a pending snapshot exists."""
        raise NotImplementedError

    def upsert_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        snapshot_json: str,
        next_cursor: str | None,
    ) -> None:
        """Create or replace pending snapshot content and cursor."""
        raise NotImplementedError

    def update_rss_processing_snapshot_cursor(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        next_cursor: str | None,
    ) -> bool:
        """Update snapshot cursor after one processed page."""
        raise NotImplementedError

    def delete_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> None:
        """Delete snapshot after full processing is complete."""
        raise NotImplementedError


@dataclass(slots=True)
class RssFetchResponse:
    """HTTP response metadata for one RSS request."""

    raw_xml: str | None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@dataclass(slots=True)
class RssFeedFetchStats:
    """Per-feed HTTP conditional fetch diagnostics for one run."""

    feed_url: str
    request_url: str
    requested_n: int
    sent_if_none_match: bool
    sent_if_modified_since: bool
    status: str
    received_etag: bool
    received_last_modified: bool
    received_items: int


@dataclass(slots=True)
class RssRunFetchStats:
    """Aggregated RSS fetch diagnostics for one run."""

    feeds_total: int = 0
    requests_conditional: int = 0
    responses_not_modified: int = 0
    responses_fetched: int = 0
    responses_with_etag: int = 0
    responses_with_last_modified: int = 0
    snapshot_articles: int = 0
    snapshot_expired: bool = False
    snapshot_restored: bool = False
    resume_cursor: str | None = None
    feeds: list[RssFeedFetchStats] = field(default_factory=list)


@dataclass(slots=True)
class RssSourceConfig:
    """RSS source settings."""

    feed_urls: tuple[str, ...]
    default_items_per_feed: int = 10_000
    per_feed_items: dict[str, int] = field(default_factory=dict)
    snapshot_max_age_seconds: int | None = 24 * 3600
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    request_timeout_seconds: float = 30.0
    state_store: RssFeedStateStore | RssProcessingSnapshotStore | None = None


class RssSource(PageCheckpointSourceAdapter):
    """Cursor-based source over one or more RSS/Atom feeds."""

    name = "rss"

    def __init__(self, config: RssSourceConfig) -> None:
        self.config = config
        self._snapshot_articles: list[SourceArticle] | None = None
        self._resume_cursor: str | None = None
        self._feed_set_hash = _build_feed_set_hash(config.feed_urls)
        self._last_run_fetch_stats = RssRunFetchStats()

    def begin_run(self) -> None:
        """Reset run-local snapshot state before a new ingestion run."""
        self._snapshot_articles = None
        self._resume_cursor = None
        self._last_run_fetch_stats = RssRunFetchStats()

    def get_last_run_fetch_stats(self) -> RssRunFetchStats:
        """Return HTTP fetch diagnostics for the latest run."""
        return self._last_run_fetch_stats

    def fetch_page(self, cursor: str | None, limit: int) -> SourcePage:
        all_articles = self._snapshot_or_fetch_articles()
        effective_cursor = cursor
        if effective_cursor is None and self._resume_cursor is not None:
            effective_cursor = self._resume_cursor
        offset = _parse_cursor_offset(effective_cursor)
        articles = all_articles[offset : offset + limit]
        next_offset = offset + limit
        next_cursor = str(next_offset) if next_offset < len(all_articles) else None
        return SourcePage(
            articles=articles,
            next_cursor=next_cursor,
            cursor=effective_cursor,
        )

    def mark_page_processed(self, *, next_cursor: str | None) -> None:
        store = self._processing_snapshot_store()
        if store is None:
            return
        if next_cursor is None:
            store.delete_rss_processing_snapshot(
                source_name=self.name,
                feed_set_hash=self._feed_set_hash,
            )
            self._resume_cursor = None
            return

        updated = store.update_rss_processing_snapshot_cursor(
            source_name=self.name,
            feed_set_hash=self._feed_set_hash,
            next_cursor=next_cursor,
        )
        if not updated and self._snapshot_articles is not None:
            logger.warning(
                "RSS snapshot row missing while advancing cursor; recreating snapshot "
                "(source=%s feed_set_hash=%s next_cursor=%s).",
                self.name,
                self._feed_set_hash,
                next_cursor,
            )
            self._save_processing_snapshot(self._snapshot_articles, next_cursor=next_cursor)
        self._resume_cursor = next_cursor

    def _snapshot_or_fetch_articles(self) -> list[SourceArticle]:
        if self._snapshot_articles is None:
            restored = self._load_processing_snapshot()
            if restored is None:
                self._snapshot_articles = self._fetch_all_articles()
                self._save_processing_snapshot(self._snapshot_articles)
            else:
                articles, resume_cursor = restored
                self._snapshot_articles = articles
                self._resume_cursor = resume_cursor
                stats = self._last_run_fetch_stats
                stats.snapshot_restored = True
                stats.resume_cursor = resume_cursor
                stats.snapshot_articles = len(articles)
                stats.feeds_total = len(self.config.feed_urls)
                for feed_url in self.config.feed_urls:
                    items_limit = self.config.per_feed_items.get(
                        feed_url,
                        self.config.default_items_per_feed,
                    )
                    stats.feeds.append(
                        RssFeedFetchStats(
                            feed_url=feed_url,
                            request_url=feed_url,
                            requested_n=items_limit,
                            sent_if_none_match=False,
                            sent_if_modified_since=False,
                            status="restored_snapshot",
                            received_etag=False,
                            received_last_modified=False,
                            received_items=0,
                        ),
                    )
        return self._snapshot_articles

    def _fetch_all_articles(self) -> list[SourceArticle]:
        articles: list[SourceArticle] = []
        stats = self._last_run_fetch_stats
        stats.feeds_total = len(self.config.feed_urls)
        for feed_url in self.config.feed_urls:
            items_limit = self.config.per_feed_items.get(
                feed_url,
                self.config.default_items_per_feed,
            )
            request_url = _effective_feed_request_url(
                feed_url=feed_url,
                items_limit=items_limit,
            )
            etag, last_modified = self._load_http_cache(request_url)
            sent_if_none_match = etag is not None
            sent_if_modified_since = last_modified is not None
            if sent_if_none_match or sent_if_modified_since:
                stats.requests_conditional += 1
            response = _coerce_fetch_response(
                self._request_feed(request_url, etag=etag, last_modified=last_modified),
            )
            parsed_items_count = 0
            parsed_feed_items: list[SourceArticle] = []
            if response.not_modified or response.raw_xml is None:
                status = "not_modified"
                stats.responses_not_modified += 1
            else:
                status = "fetched"
                stats.responses_fetched += 1
                parsed_feed_items = _parse_feed(response.raw_xml, feed_url)
                parsed_items_count = len(parsed_feed_items)
            if response.etag is not None:
                stats.responses_with_etag += 1
            if response.last_modified is not None:
                stats.responses_with_last_modified += 1
            stats.feeds.append(
                RssFeedFetchStats(
                    feed_url=feed_url,
                    request_url=request_url,
                    requested_n=items_limit,
                    sent_if_none_match=sent_if_none_match,
                    sent_if_modified_since=sent_if_modified_since,
                    status=status,
                    received_etag=response.etag is not None,
                    received_last_modified=response.last_modified is not None,
                    received_items=parsed_items_count,
                ),
            )
            self._save_http_cache(
                feed_url=request_url,
                etag=response.etag or etag,
                last_modified=response.last_modified or last_modified,
            )
            if response.not_modified or response.raw_xml is None:
                continue
            articles.extend(parsed_feed_items)
        articles.sort(key=lambda article: article.published_at, reverse=True)
        stats.snapshot_articles = len(articles)
        return articles

    def _load_http_cache(self, feed_url: str) -> tuple[str | None, str | None]:
        state_store = self.config.state_store
        if state_store is None:
            return None, None
        if not isinstance(state_store, RssFeedStateStore):
            return None, None
        return state_store.get_feed_http_cache(source_name=self.name, feed_url=feed_url)

    def _save_http_cache(
        self,
        *,
        feed_url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        state_store = self.config.state_store
        if state_store is None:
            return
        if not isinstance(state_store, RssFeedStateStore):
            return
        state_store.upsert_feed_http_cache(
            source_name=self.name,
            feed_url=feed_url,
            etag=etag,
            last_modified=last_modified,
        )

    def _processing_snapshot_store(self) -> RssProcessingSnapshotStore | None:
        state_store = self.config.state_store
        if state_store is None:
            return None
        if not isinstance(state_store, RssProcessingSnapshotStore):
            return None
        return state_store

    def _load_processing_snapshot(self) -> tuple[list[SourceArticle], str | None] | None:
        store = self._processing_snapshot_store()
        if store is None:
            return None

        row = store.get_rss_processing_snapshot(
            source_name=self.name,
            feed_set_hash=self._feed_set_hash,
        )
        if row is None:
            return None
        snapshot_json, next_cursor, updated_at = row
        if self._is_snapshot_expired(updated_at):
            store.delete_rss_processing_snapshot(
                source_name=self.name,
                feed_set_hash=self._feed_set_hash,
            )
            self._last_run_fetch_stats.snapshot_expired = True
            return None
        try:
            return _deserialize_snapshot_articles(snapshot_json), next_cursor
        except (json.JSONDecodeError, TypeError, ValueError):
            store.delete_rss_processing_snapshot(
                source_name=self.name,
                feed_set_hash=self._feed_set_hash,
            )
            return None

    def _save_processing_snapshot(
        self,
        articles: list[SourceArticle],
        *,
        next_cursor: str | None = None,
    ) -> None:
        store = self._processing_snapshot_store()
        if store is None:
            return
        store.upsert_rss_processing_snapshot(
            source_name=self.name,
            feed_set_hash=self._feed_set_hash,
            snapshot_json=_serialize_snapshot_articles(articles),
            next_cursor=next_cursor,
        )

    def _is_snapshot_expired(self, updated_at: datetime) -> bool:
        max_age_seconds = self.config.snapshot_max_age_seconds
        if max_age_seconds is None:
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        age_seconds = (datetime.now(tz=UTC) - updated_at).total_seconds()
        return age_seconds > max_age_seconds

    def _request_feed(
        self,
        feed_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> RssFetchResponse:
        attempt = 0
        last_error: TemporarySourceError | None = None
        while attempt < self.config.max_retries:
            attempt += 1
            try:
                request = Request(  # noqa: S310
                    url=feed_url,
                    headers=_build_request_headers(etag=etag, last_modified=last_modified),
                    method="GET",
                )
                with urlopen(request, timeout=self.config.request_timeout_seconds) as response:  # noqa: S310
                    return RssFetchResponse(
                        raw_xml=response.read().decode("utf-8", errors="replace"),
                        etag=_normalize_header(response.headers.get("ETag")),
                        last_modified=_normalize_header(response.headers.get("Last-Modified")),
                    )
            except HTTPError as exc:
                maybe_response, last_error = _handle_http_error(
                    error=exc,
                    etag=etag,
                    last_modified=last_modified,
                )
                if maybe_response is not None:
                    return maybe_response
            except URLError as exc:
                last_error = TemporarySourceError(
                    message=f"RSS transport error: {exc.reason}",
                    code="transport",
                )

            if last_error is None:
                break
            if attempt < self.config.max_retries:
                backoff = self.config.retry_backoff_seconds * attempt
                if last_error.retry_after is not None:
                    backoff = max(backoff, float(last_error.retry_after))
                time.sleep(backoff)

        if last_error is None:
            raise TemporarySourceError(message="RSS request failed", code="unknown")
        raise last_error


def _coerce_fetch_response(value: str | RssFetchResponse) -> RssFetchResponse:
    if isinstance(value, RssFetchResponse):
        return value
    return RssFetchResponse(raw_xml=value)


def _build_request_headers(*, etag: str | None, last_modified: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/rss+xml, application/atom+xml, application/xml",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def _handle_http_error(
    *,
    error: HTTPError,
    etag: str | None,
    last_modified: str | None,
) -> tuple[RssFetchResponse | None, TemporarySourceError | None]:
    if error.code == HTTP_NOT_MODIFIED:
        return (
            RssFetchResponse(
                raw_xml=None,
                etag=_normalize_header(error.headers.get("ETag")) or etag,
                last_modified=_normalize_header(error.headers.get("Last-Modified"))
                or last_modified,
                not_modified=True,
            ),
            None,
        )

    retry_after = _parse_retry_after(error.headers.get("Retry-After"))
    if error.code in RETRYABLE_HTTP_STATUS_CODES:
        return (
            None,
            TemporarySourceError(
                message=f"Temporary RSS HTTP error: {error.code}",
                code=str(error.code),
                retry_after=retry_after,
            ),
        )

    raise NonRetryableSourceError(
        message=f"Non-retryable RSS HTTP error: {error.code}",
        code=str(error.code),
    ) from error


def _parse_cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0


def _parse_feed(raw_xml: str, feed_url: str) -> list[SourceArticle]:
    try:
        root = ElementTree.fromstring(raw_xml)
    except ElementTree.ParseError as error:
        raise NonRetryableSourceError(
            message=f"Invalid RSS/Atom XML from {feed_url}",
            code="invalid_feed_xml",
        ) from error

    root_name = _local_name(root.tag)
    if root_name == "rss":
        return _parse_rss(root, feed_url)
    if root_name == "feed":
        return _parse_atom(root, feed_url)

    # Best effort: some feeds omit top-level conventions.
    rss_items = root.findall(".//item")
    if rss_items:
        channel = root.find(".//channel")
        container = channel if channel is not None else root
        return _parse_rss(container, feed_url)
    atom_entries = [element for element in root.iter() if _local_name(element.tag) == "entry"]
    if atom_entries:
        return _parse_atom(root, feed_url)

    raise NonRetryableSourceError(
        message=f"Unsupported feed format from {feed_url}",
        code="unsupported_feed_format",
    )


def _parse_rss(root: ElementTree.Element, feed_url: str) -> list[SourceArticle]:
    channel = root.find("channel")
    container = channel if channel is not None else root
    feed_title = _child_text(container, "title")

    results: list[SourceArticle] = []
    for item in container:
        if _local_name(item.tag) != "item":
            continue

        title = _child_text(item, "title") or "Untitled"
        link = _child_text(item, "link") or feed_url
        description = _child_text(item, "description")
        content = _child_text(item, "encoded")
        guid = _child_text(item, "guid")
        source = _child_text(item, "source") or _child_text(item, "creator")
        raw_pub_date = _child_text(item, "pubDate")
        pub_date = _parse_datetime(raw_pub_date)

        results.append(
            SourceArticle(
                external_id=_build_external_id(feed_url, guid, link, title, raw_pub_date),
                url=link,
                title=title,
                source=source or feed_title or _extract_domain(link),
                published_at=pub_date,
                content=content,
                summary=description,
                raw_payload={
                    "feed_url": feed_url,
                    "guid": guid,
                    "title": title,
                    "link": link,
                    "description": description,
                    "content": content,
                    "source": source,
                    "pub_date_raw": raw_pub_date,
                    "pub_date": pub_date.isoformat(),
                },
            ),
        )
    return results


def _parse_atom(root: ElementTree.Element, feed_url: str) -> list[SourceArticle]:
    feed_title = _child_text(root, "title")

    results: list[SourceArticle] = []
    for entry in root.iter():
        if _local_name(entry.tag) != "entry":
            continue

        title = _child_text(entry, "title") or "Untitled"
        link = _atom_link(entry) or feed_url
        summary = _child_text(entry, "summary")
        content = _child_text(entry, "content")
        entry_id = _child_text(entry, "id")
        source = _child_text(entry, "name") or _child_text(entry, "author")
        raw_published_at = _child_text(entry, "published") or _child_text(entry, "updated")
        published_at = _parse_datetime(raw_published_at)

        results.append(
            SourceArticle(
                external_id=_build_external_id(feed_url, entry_id, link, title, raw_published_at),
                url=link,
                title=title,
                source=source or feed_title or _extract_domain(link),
                published_at=published_at,
                content=content,
                summary=summary,
                raw_payload={
                    "feed_url": feed_url,
                    "id": entry_id,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "content": content,
                    "source": source,
                    "published_at_raw": raw_published_at,
                    "published_at": published_at.isoformat(),
                },
            ),
        )
    return results


def _atom_link(entry: ElementTree.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        rel = child.attrib.get("rel", "").strip().lower()
        href = child.attrib.get("href", "").strip()
        if not href:
            continue
        if not rel or rel == "alternate":
            return href
    for child in entry:
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href", "").strip()
            if href:
                return href
    return None


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    target = name.lower()
    for child in element:
        if _local_name(child.tag) != target:
            continue
        if child.text and child.text.strip():
            return child.text.strip()
        full_text = "".join(child.itertext()).strip()
        if full_text:
            return full_text
    return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _normalize_header(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _build_feed_set_hash(feed_urls: tuple[str, ...]) -> str:
    normalized = "\n".join(sorted(url.strip() for url in feed_urls if url.strip()))
    return hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324


def _effective_feed_request_url(*, feed_url: str, items_limit: int) -> str:
    parsed = urlparse(feed_url)
    host = parsed.netloc.lower()
    path = parsed.path
    if not host.endswith(INOREADER_HOST_SUFFIX) or INOREADER_STREAM_PATH_PART not in path:
        return feed_url

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["n"] = str(items_limit)
    return str(urlunparse(parsed._replace(query=urlencode(query))))


def _serialize_snapshot_articles(articles: list[SourceArticle]) -> str:
    payload = [
        {
            "external_id": item.external_id,
            "url": item.url,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat(),
            "content": item.content,
            "summary": item.summary,
            "raw_payload": item.raw_payload,
        }
        for item in articles
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deserialize_snapshot_articles(snapshot_json: str) -> list[SourceArticle]:
    raw_items = json.loads(snapshot_json)
    if not isinstance(raw_items, list):
        raise TypeError("Snapshot payload must be a JSON list")

    results: list[SourceArticle] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        published_at = _parse_datetime(str(raw.get("published_at") or ""))
        raw_payload = raw.get("raw_payload")
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        results.append(
            SourceArticle(
                external_id=str(raw.get("external_id") or ""),
                url=str(raw.get("url") or ""),
                title=str(raw.get("title") or "Untitled"),
                source=str(raw.get("source") or "unknown"),
                published_at=published_at,
                content=_nullable_string(raw.get("content")),
                summary=_nullable_string(raw.get("summary")),
                raw_payload=raw_payload,
            ),
        )
    return results


def _nullable_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(raw_value: str | None) -> datetime:
    if not raw_value:
        return UNKNOWN_PUBLISHED_AT

    try:
        parsed = parsedate_to_datetime(raw_value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        pass

    try:
        iso = datetime.fromisoformat(raw_value)
        if iso.tzinfo is None:
            return iso.replace(tzinfo=UTC)
        return iso.astimezone(UTC)
    except ValueError:
        return UNKNOWN_PUBLISHED_AT


def _build_external_id(
    feed_url: str,
    guid: str | None,
    link: str,
    title: str,
    raw_published_at: str | None,
) -> str:
    if guid and guid.strip():
        prefix = hashlib.sha1(feed_url.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]  # noqa: S324
        return f"{prefix}:{guid.strip()}"
    raw = json.dumps(
        {
            "feed_url": feed_url,
            "link": link,
            "title": title,
            "raw_published_at": (raw_published_at or "").strip(),
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324
    return f"generated:{digest}"


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or "unknown"
