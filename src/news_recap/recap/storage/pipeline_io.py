"""Pipeline input contract, workdir materialization, and resource loading.

Shared by the Prefect flow and task modules.  No Prefect imports here —
this is a plain Python module so it can be used in tests without starting
a Prefect runtime.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import msgspec

from news_recap.recap.agents.routing import RoutingDefaults, resolve_routing_for_enqueue
from news_recap.recap.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.recap.loaders.resource_cache import ResourceCache
from news_recap.recap.loaders.resource_loader import LoadedResource, ResourceLoader
from news_recap.recap.models import DigestArticle, UserPreferences
from news_recap.recap.storage.schemas import SCHEMAS_BY_TASK_TYPE
from news_recap.recap.storage.workdir import TaskWorkdirManager
from news_recap.recap.tasks.prompts import PROMPTS_BY_TASK_TYPE

logger = logging.getLogger(__name__)

_DEFAULT_MIN_RESOURCE_CHARS = 200
_PROGRESS_INTERVAL = 10


def read_task_output(workdir_root: Path, task_id: str) -> dict[str, Any]:
    """Read agent_result.json from a completed task workdir."""
    path = workdir_root / task_id / "output" / "agent_result.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"), strict=False)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in %s — returning empty result", path)
        return {}


def task_results_dir(workdir_root: Path, task_id: str) -> Path:
    """Return the results subdirectory for a task."""
    return workdir_root / task_id / "output" / "results"


@dataclass(slots=True)
class PipelineInput:
    """Deserialized contents of ``pipeline_input.json``."""

    articles: list[DigestArticle]
    preferences: UserPreferences
    routing_defaults: RoutingDefaults
    agent_override: str | None
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS


def read_pipeline_input(pipeline_dir: str) -> PipelineInput:
    """Load ``pipeline_input.json`` from *pipeline_dir*."""
    path = Path(pipeline_dir) / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    return PipelineInput(
        articles=[msgspec.convert(a, DigestArticle) for a in raw["articles"]],
        preferences=UserPreferences.from_dict(raw["preferences"]),
        routing_defaults=RoutingDefaults.from_dict(raw["routing_defaults"]),
        agent_override=raw.get("agent_override"),
        min_resource_chars=int(raw.get("min_resource_chars", _DEFAULT_MIN_RESOURCE_CHARS)),
    )


def make_task_id(step_name: str, batch: int | None = None) -> str:
    """Human-readable workdir name: ``classify``, ``classify-1``, ``classify-2``."""
    short = step_name.removeprefix("recap_")
    if batch is not None:
        return f"{short}-{batch}"
    return short


def next_batch_number(pdir: Path, step_name: str) -> int:
    """Return the next available batch number for *step_name* in *pdir*.

    Scans existing workdirs like ``enrich-1``, ``enrich-2``, … and returns
    ``max + 1`` so resumed runs don't collide with earlier batches.
    """
    prefix = step_name.removeprefix("recap_") + "-"
    highest = 0
    if pdir.is_dir():
        for d in pdir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                suffix = d.name[len(prefix) :]
                if suffix.isdigit():
                    highest = max(highest, int(suffix))
    return highest + 1


def materialize_step(  # noqa: PLR0913
    workdir_mgr: TaskWorkdirManager,
    inp: PipelineInput,
    *,
    step_name: str,
    batch: int | None = None,
    article_entries: list[ArticleIndexEntry] | None = None,
    prompt: str | None = None,
    extra_input_files: dict[str, bytes | str] | None = None,
) -> str:
    """Create a task workdir with all input files and return the task_id."""
    task_id = make_task_id(step_name, batch)
    entries = article_entries or []

    routing = resolve_routing_for_enqueue(
        defaults=inp.routing_defaults,
        task_type=step_name,
        agent_override=inp.agent_override,
        profile_override=None,
        model_override=None,
    )

    schema_hint: str | None = None
    if prompt is None:
        prompt_template = PROMPTS_BY_TASK_TYPE[step_name]
        prompt = prompt_template.format(
            preferences=inp.preferences.format_for_prompt(),
            max_headline_chars=inp.preferences.max_headline_chars,
        )
        schema_hint = SCHEMAS_BY_TASK_TYPE.get(step_name)

    workdir_mgr.materialize(
        task_id=task_id,
        task_type=step_name,
        task_input=TaskInputContract(
            task_type=step_name,
            prompt=prompt,
            metadata={"routing": routing.to_metadata()},
        ),
        articles_index=entries,
        extra_input_files=extra_input_files,
        output_schema_hint=schema_hint,
    )
    return task_id


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


def _log_load_summary(loaded_map: dict[str, LoadedResource]) -> None:
    """Log per-domain breakdown and individual failures."""
    if not loaded_map:
        return

    html_domains, html_ok, html_bytes, yt_total, yt_ok, yt_blocked, yt_bytes, failures = (
        _collect_load_stats(loaded_map)
    )

    lines = ["Resource loading summary:"]
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

    _log_load_summary(loaded_map)

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

    logger.info(
        "Resource texts: %d loaded (%d cached), %d failed, %d filtered",
        len(result),
        cache_hits,
        failed,
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
