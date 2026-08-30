#!/usr/bin/env python3
"""Quick prompt iteration tool for grouping experiments.

Usage:
    python3 scripts/experiment_prompt.py --dataset scripts/datasets/tiny.txt \\
        --agent claude --model fast
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

AGENTS = {
    "gemini": {
        "fast": "gemini --model gemini-3.7-flash --approval-mode auto_edit",
        "quality": "gemini --model gemini-3.1-pro-preview --approval-mode auto_edit",
    },
    "claude": {
        "fast": "claude -p --model haiku --permission-mode dontAsk",
        "quality": "claude -p --model claude-opus-5 --permission-mode dontAsk",
    },
}

PROMPT_TEMPLATE = textwrap.dedent("""\
    You are a senior news editor preparing a daily digest for a busy reader.
    The reader will see ONLY the block titles — and from those titles alone must
    understand what happened today. A block title is 2-4 sentences summarizing
    the key events grouped in that block.

    TARGET: produce {max_blocks} blocks (±5). This is a hard constraint — you must
    intelligently decide which stories deserve their own block and which get merged.

    EDITORIAL POLICY — FOLLOW (reader wants detailed coverage):
    {follow_policy}
    For FOLLOW topics: create separate, detailed blocks. Multiple blocks per topic
    are OK if there are distinct sub-stories.

    EDITORIAL POLICY — TRASH (discard):
    {trash_policy}
    TRASH headlines go into a single "TRASH" block at the end. No title needed.

    Everything else: group by theme. Merge minor/unrelated stories aggressively
    into broad blocks like "Brief: crime, weather, local events across the region".

    BLOCK TITLE QUALITY — this is the key deliverable:
    GOOD: "Kosovo war-crimes verdict against Serb ex-policeman upheld. Belgrade \
condemns ruling as political repression, recalls ambassador"
    GOOD: "EU suspends trade deal with US after 15% tariff announcement. Brussels \
discusses retaliatory measures, member states divided"
    GOOD: "Heavy snowfall across Serbia, temperatures at -2°C. Most roads cleared \
but Valjevo-Raška still blocked. Schools closed in 3 municipalities"
    BAD:  "Balkan Politics" — what happened?
    BAD:  "International News" — which countries? What event?

    Rules:
    - Every headline must appear in exactly one block.
    - NO singletons — every block must have at least 2 headlines.
    - Do NOT write any files. Print your output to stdout ONLY.
    - No commentary — output ONLY the block structure.

    Output format (print to stdout):
    BLOCK: <2-4 sentence summary of what happened>
    <comma-separated headline numbers>

    === HEADLINES ===
    {headlines}
""")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--agent", default="claude", choices=["claude", "gemini"])
    parser.add_argument("--model", default="fast", choices=["fast", "quality"])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=None,
        help="Target block count. Default: len(headlines)//10",
    )
    parser.add_argument("--follow", default="Russia, Serbia, war in Ukraine")
    parser.add_argument("--trash", default="horoscopes, medical advice, sports (except Russia)")
    args = parser.parse_args()

    headlines = [
        line.strip() for line in args.dataset.read_text("utf-8").splitlines() if line.strip()
    ]
    max_blocks = args.max_blocks or max(8, len(headlines) // 10)
    prompt = PROMPT_TEMPLATE.format(
        headlines="\n".join(headlines),
        max_blocks=max_blocks,
        follow_policy=args.follow,
        trash_policy=args.trash,
    )

    workdir = _PROJECT_ROOT / "docs" / "reports" / "grouping" / "_prompt_test"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    prompt_file = workdir / "prompt.txt"
    prompt_file.write_text(prompt, "utf-8")

    cmd_str = AGENTS[args.agent][args.model]
    if args.agent == "claude":
        full_cmd = f'{cmd_str} -- "Read your task from prompt.txt and execute it."'
    else:
        full_cmd = f'{cmd_str} --prompt "Read your task from prompt.txt and execute it."'

    stdout_path = workdir / "agent_stdout.log"
    stderr_path = workdir / "agent_stderr.log"

    print(f"Running {args.agent} {args.model} on {len(headlines)} headlines...")
    print(f"Workdir: {workdir}")
    start = time.monotonic()

    with stdout_path.open("w") as out_f, stderr_path.open("w") as err_f:
        proc = subprocess.Popen(  # noqa: S603 - command comes from trusted static config
            shlex.split(full_cmd),
            cwd=workdir,
            stdout=out_f,
            stderr=err_f,
            env=os.environ.copy(),
        )
        try:
            proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)

    elapsed = time.monotonic() - start
    print(f"Done in {elapsed:.1f}s (exit={proc.returncode})")
    print()

    stdout_text = stdout_path.read_text("utf-8", errors="replace")

    new_files = [
        f
        for f in workdir.iterdir()
        if f.is_file() and f.name not in {"prompt.txt", "agent_stdout.log", "agent_stderr.log"}
    ]
    if new_files:
        best = max(new_files, key=lambda f: f.stat().st_size)
        file_text = best.read_text("utf-8", errors="replace")
        if file_text.strip():
            print(f"(agent wrote to {best.name}, using that)")
            stdout_text = file_text

    print("=" * 80)
    print(stdout_text.strip())
    print("=" * 80)


if __name__ == "__main__":
    main()
