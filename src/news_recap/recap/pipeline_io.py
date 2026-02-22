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

from news_recap.brain.contracts import ArticleIndexEntry, TaskInputContract
from news_recap.brain.models import SourceCorpusEntry
from news_recap.brain.routing import RoutingDefaults, resolve_routing_for_enqueue
from news_recap.brain.workdir import TaskWorkdirManager
from news_recap.recap.prompts import PROMPTS_BY_TASK_TYPE
from news_recap.recap.resource_loader import ResourceLoader
from news_recap.recap.runner import UserPreferences
from news_recap.recap.schemas import SCHEMAS_BY_TASK_TYPE

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineInput:
    """Deserialized contents of ``pipeline_input.json``."""

    articles: list[SourceCorpusEntry]
    preferences: UserPreferences
    routing_defaults: RoutingDefaults
    agent_override: str | None


def read_pipeline_input(pipeline_dir: str) -> PipelineInput:
    """Load ``pipeline_input.json`` from *pipeline_dir*."""
    path = Path(pipeline_dir) / "pipeline_input.json"
    raw = json.loads(path.read_text("utf-8"))
    return PipelineInput(
        articles=[SourceCorpusEntry.from_dict(a) for a in raw["articles"]],
        preferences=UserPreferences.from_dict(raw["preferences"]),
        routing_defaults=RoutingDefaults.from_dict(raw["routing_defaults"]),
        agent_override=raw.get("agent_override"),
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


def load_resources(entries: list[ArticleIndexEntry]) -> dict[str, bytes | str]:
    """Fetch full-text article content via HTTP, returning a filename-to-JSON map."""
    if not entries:
        return {}
    resources: dict[str, bytes | str] = {}
    with ResourceLoader() as loader:
        for entry in entries:
            if not entry.url:
                continue
            loaded = loader.load(entry.url)
            if loaded.is_success and loaded.text:
                safe_id = entry.source_id.replace(":", "_").replace("/", "_")
                resources[f"{safe_id}.json"] = json.dumps(
                    {
                        "article_id": entry.source_id,
                        "title": entry.title,
                        "url": entry.url,
                        "source": entry.source,
                        "text": loaded.text,
                        "content_type": loaded.content_type,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                logger.warning("Failed to load %s: %s", entry.source_id, loaded.error)
    return resources
