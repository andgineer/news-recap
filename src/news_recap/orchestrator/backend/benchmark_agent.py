"""Deterministic local agent for orchestrator benchmark matrix."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from news_recap.orchestrator.contracts import (
    AgentOutputBlock,
    AgentOutputContract,
    read_articles_index,
    read_manifest,
    read_task_input,
    write_agent_output,
)


def main(argv: list[str] | None = None) -> int:
    """Run deterministic benchmark behavior based on task metadata."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--task-manifest", required=False)
    parser.add_argument("--prompt-file", required=False)
    args, _ = parser.parse_known_args(argv)

    if args.task_manifest:
        manifest_path = Path(args.task_manifest)
    elif args.prompt_file:
        manifest_path = Path(args.prompt_file).parent.parent / "meta" / "task_manifest.json"
    else:
        parser.error("Either --task-manifest or --prompt-file is required")
    manifest = read_manifest(manifest_path)
    task_input = read_task_input(Path(manifest.task_input_path))
    articles = read_articles_index(Path(manifest.articles_index_path))
    source_id = articles[0].source_id if articles else "article:missing"

    benchmark_case = str(task_input.metadata.get("benchmark_case", "success")).strip().lower()
    return _dispatch_case(
        benchmark_case=benchmark_case,
        manifest=manifest,
        source_id=source_id,
        task_input=task_input,
    )


def _dispatch_case(  # noqa: PLR0911
    *,
    benchmark_case: str,
    manifest,
    source_id: str,
    task_input,
) -> int:
    repair_mode = os.getenv("NEWS_RECAP_REPAIR_MODE", "0") == "1"
    state = _load_state(Path(manifest.workdir))

    if benchmark_case == "timeout_once":
        time.sleep(3.0)
        return 0

    if benchmark_case == "transient_retry_once":
        attempt = _coerce_int(state.get("attempt"), default=0) + 1
        state["attempt"] = attempt
        _save_state(Path(manifest.workdir), state)
        if attempt == 1:
            print("HTTP 429 too many requests, please retry", file=sys.stderr)
            return 1
        _write_valid_output(manifest=manifest, source_id=source_id, task_input=task_input)
        return 0

    if benchmark_case == "source_mapping_repair":
        if repair_mode:
            _write_valid_output(manifest=manifest, source_id=source_id, task_input=task_input)
            return 0
        Path(manifest.output_result_path).write_text(
            '{"blocks":[{"text":"missing sources","source_ids":[]}]}',
            "utf-8",
        )
        return 0

    if benchmark_case == "output_invalid_json_repair":
        if repair_mode:
            _write_valid_output(manifest=manifest, source_id=source_id, task_input=task_input)
            return 0
        Path(manifest.output_result_path).write_text('{"blocks":[', "utf-8")
        return 0

    if benchmark_case == "non_retryable_failure":
        print("permission denied", file=sys.stderr)
        return 2

    _write_valid_output(manifest=manifest, source_id=source_id, task_input=task_input)
    return 0


def _write_valid_output(*, manifest, source_id: str, task_input) -> None:
    payload = AgentOutputContract(
        blocks=[
            AgentOutputBlock(
                text=f"Benchmark output for {task_input.task_type}",
                source_ids=[source_id],
            ),
        ],
        metadata={
            "backend": "benchmark_agent",
            "repair_mode": os.getenv("NEWS_RECAP_REPAIR_MODE", "0"),
        },
    )
    write_agent_output(Path(manifest.output_result_path), payload)


def _state_path(workdir: Path) -> Path:
    return workdir / "benchmark_state.json"


def _load_state(workdir: Path) -> dict[str, object]:
    path = _state_path(workdir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _save_state(workdir: Path, payload: dict[str, object]) -> None:
    path = _state_path(workdir)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), "utf-8")


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
