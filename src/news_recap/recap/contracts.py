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
        )
    except Exception as error:  # noqa: BLE001
        raise ValueError(f"Invalid task manifest at {path}") from error


def write_manifest(path: Path, manifest: TaskManifest) -> None:
    """Persist task manifest."""

    write_json(path, asdict(manifest))
