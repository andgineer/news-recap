"""Pipeline input contract and resource loading."""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import msgspec

from news_recap.recap.agents.routing import RoutingDefaults
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.loaders.resource_cache import ResourceCache
from news_recap.recap.loaders.resource_loader import LoadedResource, ResourceLoader
from news_recap.recap.models import DigestArticle, UserPreferences
from news_recap.recap.storage.workdir import (  # noqa: F401 — re-exports
    make_task_id,
    materialize_step,
    next_batch_number,
)
from news_recap.recap.tasks.prompts import PromptBackend

logger = logging.getLogger(__name__)

_DEFAULT_MIN_RESOURCE_CHARS = 200
_PROGRESS_INTERVAL = 10


@dataclass(slots=True)
class PipelineInput:
    """Deserialized contents of ``pipeline_input.json``."""

    articles: list[DigestArticle]
    preferences: UserPreferences
    routing_defaults: RoutingDefaults
    agent_override: str | None
    data_dir: str
    run_date: str
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS
    dedup_threshold: float = 0.90
    dedup_model_name: str = "intfloat/multilingual-e5-small"
    coverage_start: str | None = None
    coverage_end: str | None = None
    use_api_key: bool = False
    selection_params: dict[str, object] | None = None

    @property
    def execution_backend(self) -> str:
        return self.routing_defaults.execution_backend

    @property
    def prompt_backend(self) -> PromptBackend:
        return PromptBackend(self.routing_defaults.execution_backend)

    @property
    def active_agent(self) -> str:
        return (self.agent_override or self.routing_defaults.default_agent).strip().lower()

    def effective_max_parallel(self, task_max: int) -> int:
        """Return the effective concurrency: ``min(task_max, agent_limit)``.

        Uses the active agent (override or default) to look up the per-vendor
        cap from ``routing_defaults.agent_max_parallel``.
        """
        vendor_max = self.routing_defaults.agent_max_parallel.get(self.active_agent, task_max)
        return min(task_max, vendor_max)

    @property
    def launch_delay(self) -> float:
        """Seconds to wait between launching concurrent agents for this vendor."""
        return self.routing_defaults.agent_launch_delay.get(self.active_agent, 0.0)


def resource_cache_dir(data_dir: str, run_date: str) -> Path:
    """Return the date-sharded resource cache directory."""
    return Path(data_dir) / "resources" / run_date


def read_pipeline_input(pipeline_dir: str) -> PipelineInput:
    """Load ``pipeline_input.json`` from *pipeline_dir*."""
    path = Path(pipeline_dir) / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    return PipelineInput(
        articles=[msgspec.convert(a, DigestArticle) for a in raw["articles"]],
        preferences=UserPreferences.from_dict(raw["preferences"]),
        routing_defaults=RoutingDefaults.from_dict(raw["routing_defaults"]),
        agent_override=raw.get("agent_override"),
        data_dir=raw.get("data_dir", str(Path.home() / ".news_recap_data")),
        run_date=raw["run_date"],
        min_resource_chars=int(raw.get("min_resource_chars", _DEFAULT_MIN_RESOURCE_CHARS)),
        dedup_threshold=float(raw.get("dedup_threshold", 0.90)),
        dedup_model_name=raw.get("dedup_model_name", "intfloat/multilingual-e5-small"),
        coverage_start=raw.get("coverage_start"),
        coverage_end=raw.get("coverage_end"),
        use_api_key=bool(raw.get("use_api_key", False)),
        selection_params=raw.get("selection_params"),
    )


_MAX_LOGGED_FAILURES = 20


def _log_load_failures(
    failures: list[tuple[str, str, str | None]],
) -> None:
    if not failures:
        return
    shown = failures[:_MAX_LOGGED_FAILURES]
    lines = [f"Failed resources ({len(failures)} total):"]
    for sid, url, error in shown:
        lines.append(f"  {sid} ({url}): {error}")
    if len(failures) > _MAX_LOGGED_FAILURES:
        lines.append(f"  ... and {len(failures) - _MAX_LOGGED_FAILURES} more")
    logger.warning("\n".join(lines))


def _collect_load_stats(
    loaded_map: dict[str, LoadedResource],
) -> tuple[
    Counter[str],
    Counter[str],
    Counter[str],
    int,
    int,
    int,
    int,
    list[tuple[str, str, str | None]],
]:
    html_domains: Counter[str] = Counter()
    html_ok: Counter[str] = Counter()
    html_bytes: Counter[str] = Counter()
    yt_total = yt_ok = yt_blocked = yt_bytes = 0
    failures: list[tuple[str, str, str | None]] = []

    for source_id, loaded in loaded_map.items():
        if not loaded.is_success and not loaded.is_blocked:
            failures.append((source_id, loaded.url, loaded.error))
        if loaded.content_type.startswith("youtube/"):
            yt_total += 1
            if loaded.is_success:
                yt_ok += 1
                yt_bytes += len(loaded.text)
            elif loaded.is_blocked:
                yt_blocked += 1
        else:
            domain = urlparse(loaded.url).netloc.lower()
            html_domains[domain] += 1
            if loaded.is_success:
                html_ok[domain] += 1
                html_bytes[domain] += len(loaded.text)

    return html_domains, html_ok, html_bytes, yt_total, yt_ok, yt_blocked, yt_bytes, failures


def _log_load_summary(loaded_map: dict[str, LoadedResource], cache_hits: int = 0) -> None:
    """Log per-domain breakdown and individual failures."""
    if not loaded_map:
        return

    html_domains, html_ok, html_bytes, yt_total, yt_ok, yt_blocked, yt_bytes, failures = (
        _collect_load_stats(loaded_map)
    )

    header = "Resource loading summary:"
    if cache_hits:
        header += f" ({cache_hits}/{len(loaded_map)} from cache)"
    lines = [header]
    if yt_total:
        lines.append(
            f"  YouTube: {yt_ok}/{yt_total} transcripts"
            f" ({yt_bytes / 1024:.0f} KB)" + (f", {yt_blocked} blocked" if yt_blocked else ""),
        )
    top = html_domains.most_common(10)
    if top:
        lines.append(f"  HTML domains (top {len(top)}):")
        for domain, count in top:
            ok = html_ok[domain]
            kb = html_bytes[domain] / 1024
            lines.append(f"    {domain}: {ok}/{count} loaded ({kb:.0f} KB)")

    logger.info("\n".join(lines))
    _log_load_failures(failures)


def load_resource_texts(
    entries: list[ArticleIndexEntry],
    *,
    cache_dir: Path | None = None,
    loader: ResourceLoader | None = None,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
) -> dict[str, tuple[str, str]]:
    """Fetch full-text content, returning ``{source_id: (title, text)}``.

    Like ``load_resources`` but returns structured data for prompt
    embedding instead of JSON files for workdir materialization.
    """
    url_entries = [(e.source_id, e.url) for e in entries if e.url]
    if not url_entries:
        return {}

    total = len(url_entries)
    logger.info("Loading resource texts for %d articles…", total)

    owns_loader = loader is None
    loader = loader or ResourceLoader()
    try:
        loaded_map, cache_hits = _fetch_all(url_entries, loader, cache_dir)
    finally:
        if owns_loader:
            loader.close()

    _log_load_summary(loaded_map, cache_hits)

    entry_map = {e.source_id: e for e in entries}
    result: dict[str, tuple[str, str]] = {}
    failed = 0
    filtered = 0

    for source_id, loaded in loaded_map.items():
        if not loaded.is_success or not loaded.text:
            failed += 1
        else:
            threshold = _quality_threshold(loaded, min_resource_chars)
            if len(loaded.text) < threshold:
                filtered += 1
            else:
                entry = entry_map[source_id]
                result[source_id] = (entry.title, loaded.text)

    failed_tag = f"[red]{failed}[/red]" if failed else "0"
    logger.info(
        "Resource texts: [green]%d loaded[/green] (%d cached), %s failed, %d filtered",
        len(result),
        cache_hits,
        failed_tag,
        filtered,
    )
    return result


def load_cached_resource_texts(
    entries: list[ArticleIndexEntry],
    *,
    cache_dir: Path,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
) -> dict[str, tuple[str, str]]:
    """Read previously-loaded texts from ``ResourceCache`` (no network).

    Returns ``{source_id: (title, text)}`` for entries that have a valid
    cached resource.  Articles without a cache hit are silently skipped.
    """
    cache = ResourceCache(cache_dir)
    result: dict[str, tuple[str, str]] = {}

    for entry in entries:
        if not entry.url:
            continue
        cached = cache.get(entry.source_id, expected_url=entry.url)
        if cached is None or not cached.is_success or not cached.text:
            continue
        threshold = _quality_threshold(cached, min_resource_chars)
        if len(cached.text) < threshold:
            continue
        result[entry.source_id] = (entry.title, cached.text)

    return result


def _fetch_all(
    entries: list[tuple[str, str]],
    loader: ResourceLoader,
    cache_dir: Path | None,
) -> tuple[dict[str, LoadedResource], int]:
    """Fetch resources with optional cache, returning ``(results, cache_hits)``."""
    if cache_dir is not None:
        cache = ResourceCache(cache_dir)
        return cache.get_or_load(entries, loader)
    return loader.load_batch(entries), 0


def _quality_threshold(loaded: LoadedResource, base: int) -> int:
    """YouTube transcripts use half the threshold (short captions are still useful)."""
    if loaded.content_type.startswith("youtube/"):
        return max(1, base // 2)
    return base
