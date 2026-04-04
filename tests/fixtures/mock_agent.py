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
    articles_index_path = Path("input") / "articles_index.json"
    if not articles_index_path.exists():
        sys.exit(0)

    raw = json.loads(articles_index_path.read_text("utf-8"))
    articles = raw if isinstance(raw, list) else raw.get("articles", [])

    for i, article in enumerate(articles):
        source_id = article.get("source_id", f"unknown_{i}")
        r = i % 10
        if r == 0:
            verdict = "exclude"
        elif r == 1:
            verdict = "enrich"
        else:
            verdict = "ok"
        print(f"{source_id}\t{verdict}")

    sys.exit(0)


if __name__ == "__main__":
    main()
