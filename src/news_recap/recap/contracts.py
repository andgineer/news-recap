"""File-based contracts for orchestrator task inputs and outputs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ArticleIndexEntry:
    """One allowed source entry for strict source mapping."""

    source_id: str
    title: str
    url: str
    source: str = ""
    published_at: str | None = None


@dataclass(slots=True)
class TaskInputContract:
    """Task input payload consumed by the backend."""

    task_type: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentOutputBlock:
    """One output block with mandatory source mapping."""

    text: str
    source_ids: list[str]


@dataclass(slots=True)
class AgentOutputContract:
    """Top-level output payload produced by backend."""

    blocks: list[AgentOutputBlock]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskManifest:
    """Manifest stored with each queued task."""

    contract_version: int
    task_id: str
    task_type: str
    workdir: str
    task_input_path: str
    articles_index_path: str
    output_result_path: str
    output_stdout_path: str
    output_stderr_path: str
    continuity_summary_path: str | None = None
    retrieval_context_path: str | None = None
    story_context_path: str | None = None
    input_resources_dir: str | None = None
    output_results_dir: str | None = None
    output_schema_hint: str | None = None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON payload using deterministic formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON document and validate top-level object type."""

    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return payload


def write_task_input(path: Path, payload: TaskInputContract) -> None:
    """Serialize task input contract."""

    write_json(path, asdict(payload))


def read_task_input(path: Path) -> TaskInputContract:
    """Deserialize and validate task input contract."""

    raw = load_json(path)
    task_type = raw.get("task_type")
    prompt = raw.get("prompt")
    metadata = raw.get("metadata", {})
    if not isinstance(task_type, str) or not task_type.strip():
        raise ValueError("task_input.task_type must be a non-empty string")
    if not isinstance(prompt, str):
        raise TypeError("task_input.prompt must be a string")
    if not isinstance(metadata, dict):
        raise TypeError("task_input.metadata must be an object")
    return TaskInputContract(task_type=task_type, prompt=prompt, metadata=metadata)


def write_articles_index(path: Path, articles: list[ArticleIndexEntry]) -> None:
    """Serialize allowed articles index for strict source mapping."""

    write_json(path, {"articles": [asdict(entry) for entry in articles]})


def read_articles_index(path: Path) -> list[ArticleIndexEntry]:
    """Deserialize allowed articles index."""

    raw = load_json(path)
    raw_articles = raw.get("articles")
    if not isinstance(raw_articles, list):
        raise TypeError("articles_index.articles must be an array")

    entries: list[ArticleIndexEntry] = []
    for item in raw_articles:
        if not isinstance(item, dict):
            raise TypeError("articles_index entry must be an object")
        source_id = item.get("source_id")
        title = item.get("title")
        url = item.get("url")
        source = item.get("source", "")
        published_at = item.get("published_at")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("articles_index.source_id must be a non-empty string")
        if not isinstance(title, str):
            raise TypeError("articles_index.title must be a string")
        if not isinstance(url, str):
            raise TypeError("articles_index.url must be a string")
        if not isinstance(source, str):
            raise TypeError("articles_index.source must be a string")
        if published_at is not None and not isinstance(published_at, str):
            raise ValueError("articles_index.published_at must be a string when provided")
        entries.append(
            ArticleIndexEntry(
                source_id=source_id,
                title=title,
                url=url,
                source=source,
                published_at=published_at,
            ),
        )
    return entries


def write_agent_output(path: Path, payload: AgentOutputContract) -> None:
    """Serialize backend output contract."""

    write_json(path, asdict(payload))


def read_manifest(path: Path) -> TaskManifest:
    """Load and validate task manifest."""

    raw = load_json(path)
    required = {
        "task_id",
        "task_type",
        "workdir",
        "task_input_path",
        "articles_index_path",
        "output_result_path",
        "output_stdout_path",
        "output_stderr_path",
    }
    missing = [key for key in sorted(required) if key not in raw]
    if missing:
        raise ValueError(f"Manifest missing required fields: {', '.join(missing)}")

    contract_version_raw = raw.get("contract_version", 1)
    if not isinstance(contract_version_raw, int) or contract_version_raw < 1:
        raise ValueError("task_manifest.contract_version must be an integer >= 1")

    optional_str_fields = (
        "continuity_summary_path",
        "retrieval_context_path",
        "story_context_path",
        "input_resources_dir",
        "output_results_dir",
        "output_schema_hint",
    )
    optional_values: dict[str, str | None] = {}
    for field_name in optional_str_fields:
        field_value = raw.get(field_name)
        if field_value is not None and not isinstance(field_value, str):
            raise ValueError(f"task_manifest.{field_name} must be a string when provided")
        optional_values[field_name] = str(field_value) if field_value is not None else None

    try:
        return TaskManifest(
            contract_version=int(contract_version_raw),
            task_id=str(raw["task_id"]),
            task_type=str(raw["task_type"]),
            workdir=str(raw["workdir"]),
            task_input_path=str(raw["task_input_path"]),
            articles_index_path=str(raw["articles_index_path"]),
            output_result_path=str(raw["output_result_path"]),
            output_stdout_path=str(raw["output_stdout_path"]),
            output_stderr_path=str(raw["output_stderr_path"]),
            **optional_values,
        )
    except Exception as error:  # noqa: BLE001
        raise ValueError(f"Invalid task manifest at {path}") from error


def write_manifest(path: Path, manifest: TaskManifest) -> None:
    """Persist task manifest."""

    write_json(path, asdict(manifest))
