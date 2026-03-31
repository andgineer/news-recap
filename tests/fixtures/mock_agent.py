#!/usr/bin/env python3
"""Mock LLM agent for local testing without real AI calls.

Reads articles_index.json from the task workdir and prints classify verdicts
to stdout in the same format the real agent would use: ID<TAB>VERDICT.

Distribution: ~80% ok, ~10% exclude, ~10% enrich (deterministic by article index).

Usage — override the gemini command template in Settings, then run normally:

    # In conftest.py or test setup:
    settings.orchestrator.gemini_command_template = (
        "python3 tests/fixtures/mock_agent.py --model {model} {prompt_file}"
    )
    # Then: news-recap create --agent gemini --limit 20

The script accepts (and ignores) any positional args so it fits any command template.
cwd is set to the task workdir by task_ai_agent.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    # cli_backend sets cwd=manifest.workdir — read articles from there
    articles_index_path = Path("input") / "articles_index.json"
    if not articles_index_path.exists():
        # Not a classify task (enrich/group/etc.) — write empty JSON result
        result_path = _find_output_result_path()
        if result_path:
            result_path.write_text('{"status": "mock", "processed": 0}', "utf-8")
        sys.exit(0)

    raw = json.loads(articles_index_path.read_text("utf-8"))
    articles = raw if isinstance(raw, list) else raw.get("articles", [])

    for i, article in enumerate(articles):
        source_id = article.get("source_id", f"unknown_{i}")
        # Deterministic distribution: 80% ok, 10% exclude, 10% enrich
        r = i % 10
        if r == 0:
            verdict = "exclude"
        elif r == 1:
            verdict = "enrich"
        else:
            verdict = "ok"
        print(f"{source_id}\t{verdict}")

    sys.exit(0)


def _find_output_result_path() -> Path | None:
    """Find output_result_path from task_manifest.json if present."""
    manifest_path = Path("meta") / "task_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
        p = manifest.get("output_result_path")
        if p:
            out = Path(p)
            out.parent.mkdir(parents=True, exist_ok=True)
            return out
    except Exception:  # noqa: BLE001
        pass
    return None


if __name__ == "__main__":
    main()
