"""File-based resource cache with daily sharding.

Stores loaded resources (successes *and* failures) as JSON files so that
pipeline steps share fetched content without re-downloading or re-hitting
APIs that already returned errors.  The cache directory is provided by
the caller (typically ``{data_dir}/resources/{run_date}/``).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from news_recap.recap.loaders.resource_loader import LoadedResource, ResourceLoader

logger = logging.getLogger(__name__)


def _safe_id(source_id: str) -> str:
    return source_id.replace(":", "_").replace("/", "_")


class ResourceCache:
    """Read-through cache backed by JSON files in a caller-provided directory."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, source_id: str, *, expected_url: str) -> LoadedResource | None:
        """Return a cached resource if it exists, the URL matches, and the file is valid."""
        path = self._dir / f"{_safe_id(source_id)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("Corrupt cache entry for %s — discarding", source_id)
            return None

        if not isinstance(data, dict):
            logger.debug("Invalid cache shape for %s — discarding", source_id)
            return None

        if data.get("url") != expected_url:
            logger.debug(
                "Cache URL mismatch for %s: cached=%s expected=%s — discarding",
                source_id,
                data.get("url"),
                expected_url,
            )
            return None

        return LoadedResource(
            url=data["url"],
            text=data.get("text", ""),
            content_type=data.get("content_type", ""),
            is_success=data.get("is_success", True),
            error=data.get("error"),
        )

    def put(self, source_id: str, resource: LoadedResource) -> None:
        """Cache a load result (success or permanent failure).

        Temporary failures (IP blocks) are **not** cached so that the next
        pipeline run retries them.
        """
        if resource.is_blocked:
            return
        path = self._dir / f"{_safe_id(source_id)}.json"
        data = {
            "url": resource.url,
            "text": resource.text,
            "content_type": resource.content_type,
            "is_success": resource.is_success,
            "error": resource.error,
            "fetched_at": datetime.now(tz=UTC).isoformat(),
        }
        path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

    def get_or_load(
        self,
        entries: list[tuple[str, str]],
        loader: ResourceLoader,
    ) -> tuple[dict[str, LoadedResource], int]:
        """Check cache first, batch-fetch missing entries, cache successes.

        Returns ``(results_dict, cache_hits)`` where *results_dict* is keyed
        by ``source_id`` and *cache_hits* is the number served from cache.
        """
        results: dict[str, LoadedResource] = {}
        to_fetch: list[tuple[str, str]] = []
        cache_hits = 0

        for source_id, url in entries:
            cached = self.get(source_id, expected_url=url)
            if cached is not None:
                results[source_id] = cached
                cache_hits += 1
            else:
                to_fetch.append((source_id, url))

        if to_fetch:
            fetched = loader.load_batch(to_fetch)
            for source_id, resource in fetched.items():
                self.put(source_id, resource)
                results[source_id] = resource

        return results, cache_hits
