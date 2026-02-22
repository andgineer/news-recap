"""Local mock agent that produces deterministic output without calling any LLM.

Used for integration tests and for debugging Prefect flows without burning
tokens.  Detects task type from the prompt and produces appropriate output:

- **classify**: prints ``N<TAB>ok`` verdict lines to stdout (one per headline)
- **other tasks**: writes a minimal ``agent_result.json`` with the prompt echoed back

Usage (standalone)::

    python -m news_recap.recap.backend.echo_agent --prompt-file input/task_prompt.txt

Or via command template (set in env or Settings)::

    NEWS_RECAP_GEMINI_COMMAND_TEMPLATE="python -m news_recap.recap.backend.echo_agent \
        --prompt-file {prompt_file}"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from news_recap.recap.contracts import (
    AgentOutputBlock,
    AgentOutputContract,
    read_articles_index,
    read_manifest,
    read_task_input,
    write_agent_output,
)


def _count_headlines(prompt: str) -> int:
    """Count numbered headline lines (``N<TAB>title``) in a classify prompt."""
    return len(re.findall(r"^\d+\t", prompt, re.MULTILINE))


def _handle_classify(prompt: str) -> None:
    """Print ``N<TAB>ok`` for every headline found in the prompt."""
    n = _count_headlines(prompt)
    for i in range(1, n + 1):
        print(f"{i}\tok")


def main(argv: list[str] | None = None) -> int:
    """Run local deterministic mock agent."""

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
    workdir = Path(manifest.workdir)
    if not workdir.is_absolute():
        workdir = manifest_path.parent.parent

    task_input = read_task_input(workdir / "input" / "task_input.json")
    articles_path = workdir / "input" / "articles_index.json"
    articles = read_articles_index(articles_path) if articles_path.exists() else []

    prompt = task_input.prompt.strip()

    if task_input.task_type == "recap_classify" or _count_headlines(prompt) > 0:
        _handle_classify(prompt)

    source_ids = [articles[0].source_id] if articles else []
    text = prompt or f"{task_input.task_type} output"
    payload = AgentOutputContract(
        blocks=[AgentOutputBlock(text=text, source_ids=source_ids)],
        metadata={
            "backend": "echo_agent",
            "repair_mode": os.getenv("NEWS_RECAP_REPAIR_MODE", "0"),
        },
    )
    output_path = workdir / "output" / "agent_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_agent_output(output_path, payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
