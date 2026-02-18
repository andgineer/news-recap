"""Local demo agent for CLI backend integration tests."""

from __future__ import annotations

import argparse
import os
import sys
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
    """Run local deterministic demo generation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--task-manifest", required=True)
    args = parser.parse_args(argv)

    manifest_path = Path(args.task_manifest)
    manifest = read_manifest(manifest_path)
    task_input = read_task_input(Path(manifest.task_input_path))
    articles = read_articles_index(Path(manifest.articles_index_path))

    source_ids = [articles[0].source_id] if articles else []
    text = task_input.prompt.strip() or f"{task_input.task_type} output"
    payload = AgentOutputContract(
        blocks=[AgentOutputBlock(text=text, source_ids=source_ids)],
        metadata={
            "backend": "echo_agent",
            "repair_mode": os.getenv("NEWS_RECAP_REPAIR_MODE", "0"),
        },
    )
    write_agent_output(Path(manifest.output_result_path), payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
