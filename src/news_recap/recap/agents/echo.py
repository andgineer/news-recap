"""Local mock agent that produces deterministic output without calling any LLM.

Used for integration tests and for debugging Prefect flows without burning
tokens.  Detects task type from the prompt and produces appropriate output:

- **classify**: prints ``N<TAB>ok`` verdict lines to stdout (one per headline)
- **other tasks**: echoes the prompt to stdout

Usage (standalone)::

    python -m news_recap.recap.agents.echo --prompt-file input/task_prompt.txt

Or via command template (set in env or Settings)::

    NEWS_RECAP_GEMINI_COMMAND_TEMPLATE="python -m news_recap.recap.agents.echo \
        --prompt-file {prompt_file}"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


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
    parser.add_argument("--prompt-file", required=True)
    args, _ = parser.parse_known_args(argv)

    prompt = Path(args.prompt_file).read_text("utf-8").strip()

    if _count_headlines(prompt) > 0:
        _handle_classify(prompt)
    else:
        print(prompt)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
