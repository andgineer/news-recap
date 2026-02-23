"""Pipeline input contract, workdir materialization, and resource loading.

Shared by the Prefect flow and task modules.  No Prefect imports here —
this is a plain Python module so it can be used in tests without starting
a Prefect runtime.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def load_resources(
    entries: list[ArticleIndexEntry],
    *,
    cache_dir: Path | None = None,
    loader: ResourceLoader | None = None,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
) -> dict[str, bytes | str]:
    """Fetch full-text article content, returning a filename-to-JSON map.

    Fetches URLs concurrently via ``ResourceLoader.load_batch()``.
    When *cache_dir* is provided, uses a file-based cache so that
    ``Enrich`` and ``EnrichFull`` share fetched content.
    """
    url_entries = [(e.source_id, e.url) for e in entries if e.url]
    if not url_entries:
        return {}

    total = len(url_entries)
    logger.info("Loading resources for %d articles…", total)

    owns_loader = loader is None
    loader = loader or ResourceLoader()
    try:
        loaded_map, cache_hits = _fetch_all(url_entries, loader, cache_dir)
    finally:
        if owns_loader:
            loader.close()

    entry_map = {e.source_id: e for e in entries}
    resources: dict[str, bytes | str] = {}
    failed = 0
    filtered = 0

    for processed, (source_id, loaded) in enumerate(loaded_map.items(), 1):
        if not loaded.is_success or not loaded.text:
            failed += 1
            logger.warning("Failed to load %s: %s", source_id, loaded.error)
        else:
            threshold = _quality_threshold(loaded, min_resource_chars)
            if len(loaded.text) < threshold:
                filtered += 1
                logger.warning(
                    "Skipping %s: text too short (%d < %d chars)",
                    source_id,
                    len(loaded.text),
                    threshold,
                )
            else:
                entry = entry_map[source_id]
                safe_id = source_id.replace(":", "_").replace("/", "_")
                resources[f"{safe_id}.json"] = json.dumps(
                    {
                        "article_id": source_id,
                        "title": entry.title,
                        "url": entry.url,
                        "source": entry.source,
                        "text": loaded.text,
                        "content_type": loaded.content_type,
                    },
                    ensure_ascii=False,
                    indent=2,
                )

        if processed % _PROGRESS_INTERVAL == 0:
            logger.info(
                "Resources: %d/%d processed, %d loaded, %d failed, %d cached",
                processed,
                total,
                len(resources),
                failed,
                cache_hits,
            )

    logger.info(
        "Resource loading complete: %d loaded (%d cached), %d failed, %d below quality threshold",
        len(resources),
        cache_hits,
        failed,
        filtered,
    )
    return resources


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
