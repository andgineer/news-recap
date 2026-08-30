#!/usr/bin/env python3
"""Experiment runner for grouping approaches.

Usage:
    python scripts/experiment_grouping.py \
        --approach iterative \
        --agent gemini \
        --model fast \
        --dataset scripts/datasets/small.txt \
        --batch-size 100 \
        --tag "iter-gemini-fast-200-b100"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GIANT_BLOCK_SIZE = 30
_BLOCK_ARTICLE_PREVIEW = 10

AGENTS = {
    "gemini": {
        "flash": {
            "cmd": "gemini --model gemini-3.7-flash --approval-mode auto_edit",
            "prompt_arg": "--prompt",
        },
        "flash-lite": {
            "cmd": "gemini --model gemini-3.5-flash-lite --approval-mode auto_edit",
            "prompt_arg": "--prompt",
        },
        "pro": {
            "cmd": "gemini --model gemini-3.1-pro-preview --approval-mode auto_edit",
            "prompt_arg": "--prompt",
        },
        "fast": {
            "cmd": "gemini --model gemini-3.7-flash --approval-mode auto_edit",
            "prompt_arg": "--prompt",
        },
        "quality": {
            "cmd": "gemini --model gemini-3.1-pro-preview --approval-mode auto_edit",
            "prompt_arg": "--prompt",
        },
    },
    "claude": {
        "sonnet": {
            "cmd": "claude -p --model claude-sonnet-5 --effort low --permission-mode dontAsk",
            "prompt_arg": "--",
        },
        "opus": {
            "cmd": "claude -p --model claude-opus-5 --permission-mode dontAsk",
            "prompt_arg": "--",
        },
        "fast": {
            "cmd": "claude -p --model haiku --permission-mode dontAsk",
            "prompt_arg": "--",
        },
        "quality": {
            "cmd": "claude -p --model claude-opus-5 --permission-mode dontAsk",
            "prompt_arg": "--",
        },
    },
    "codex": {
        "low": {
            "cmd": (
                "codex exec --sandbox workspace-write"
                " -c sandbox_workspace_write.network_access=true"
                " --model gpt-5.6-luna -c model_reasoning_effort=low"
            ),
            "prompt_arg": "",
        },
        "medium": {
            "cmd": (
                "codex exec --sandbox workspace-write"
                " -c sandbox_workspace_write.network_access=true"
                " --model gpt-5.6-terra -c model_reasoning_effort=low"
            ),
            "prompt_arg": "",
        },
        "high": {
            "cmd": (
                "codex exec --sandbox workspace-write"
                " -c sandbox_workspace_write.network_access=true"
                " --model gpt-5.6-sol -c model_reasoning_effort=low"
            ),
            "prompt_arg": "",
        },
        "fast": {
            "cmd": (
                "codex exec --sandbox workspace-write"
                " -c sandbox_workspace_write.network_access=true"
                " --model gpt-5.6-luna -c model_reasoning_effort=low"
            ),
            "prompt_arg": "",
        },
        "quality": {
            "cmd": (
                "codex exec --sandbox workspace-write"
                " -c sandbox_workspace_write.network_access=true"
                " --model gpt-5.6-sol -c model_reasoning_effort=low"
            ),
            "prompt_arg": "",
        },
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SINGLE_PASS_PROMPT = textwrap.dedent("""\
    You are a news editor organizing a daily digest.

    Group the numbered headlines below into thematic BLOCKS.
    Each block should cover one topic or closely related events.

    Block titles are the MOST important part. The reader will scan ONLY the titles
    to decide what to read. A good title tells the reader exactly what happened,
    so they can skip the block if the topic is not relevant to them.
    BAD:  "Balkan Politics" (too vague — what about Balkan politics?)
    GOOD: "Kosovo war-crimes verdict sparks Serbia-Kosovo tensions"
    GOOD: "US steel tariffs hit EU — retaliatory measures discussed"

    Rules:
    - Every headline must appear in exactly one block.
    - A block should have 2-30 headlines. If a topic has more, split into subtopics.
    - Blocks with just 1 headline are acceptable only if the topic is truly unique.
    - Do NOT write any files. Print your output to stdout ONLY.
    - No commentary, no explanations — output ONLY the block structure.

    Output format (print to stdout, one block per section):
    BLOCK: <block title>
    <comma-separated headline numbers>

    === HEADLINES ===
    {headlines}
""")

TWO_STAGE_EVENTS_PROMPT = textwrap.dedent("""\
    You are a news editor. Group these numbered headlines into EVENTS.
    An event is a single real-world fact or story (e.g. "arrest of person X",
    "earthquake in region Y").

    Rules:
    - Every headline must appear in exactly one event.
    - Multiple headlines about the same story → one event.
    - Give each event a short factual title.
    - Do NOT write any files. Print your output to stdout ONLY.
    - No commentary — output ONLY the event structure.

    Output format (print to stdout):
    EVENT: <event title>
    <comma-separated headline numbers>

    === HEADLINES ===
    {headlines}
""")

TWO_STAGE_BLOCKS_PROMPT = textwrap.dedent("""\
    You are a news editor organizing events into digest blocks.
    Group these events into thematic BLOCKS for a daily digest.

    Rules:
    - Every event must appear in exactly one block.
    - A block should have 2-15 events. Split large topics into subtopics.
    - Give each block a short, informative title.
    - Do NOT write any files. Print your output to stdout ONLY.
    - No commentary — output ONLY the block structure.

    Output format (print to stdout):
    BLOCK: <block title>
    <comma-separated event numbers>

    === EVENTS ===
    {events}
""")

ITERATIVE_BATCH_PROMPT_A = textwrap.dedent("""\
    You are a senior news editor building a daily digest incrementally.
    You have existing blocks and a new batch of headlines to process.

    The reader will see ONLY block titles and from those alone must understand
    what happened today. A block title is 2-4 sentences summarizing the events
    grouped in that block.

    A good block = a group of headlines whose combined story reads naturally
    in 2-4 sentences. If you can't write a coherent summary — the block is
    too broad, split it. If the summary has only one fact — merge with related.

    FOLLOW (reader cares — don't compress too aggressively, titles should
    convey what specifically happened):
    {follow_policy}

    TRASH — assign to the TRASH block:
    {trash_policy}

    Target total blocks: around {max_blocks}. Prefer adding to existing blocks
    over creating new ones. Merge aggressively for non-FOLLOW topics.

    When adding headlines to a block, UPDATE the block title to reflect the
    fuller picture.

    GOOD title: "Kosovo war-crimes verdict upheld. Belgrade condemns ruling,
    recalls ambassador. Pristina says justice served after 25 years"
    BAD title: "Balkan Politics"

    Do NOT write any files. Print your output to stdout ONLY.
    No commentary — output ONLY assignments.

    Output format:
    BLOCK <N>: <updated 2-4 sentence title>
    ADD: <comma-separated new headline numbers>

    NEW BLOCK: <2-4 sentence title>
    <comma-separated new headline numbers>

    {existing_blocks}

    === NEW HEADLINES ===
    {headlines}
""")

ITERATIVE_BATCH_PROMPT_B = textwrap.dedent("""\
    You are a senior news editor. Compress new headlines into around {max_blocks}
    blocks total — today's main stories. You have existing blocks and a new batch.

    Each block = a coherent story told in 2-4 sentences. That IS the block title.
    The reader reads ONLY titles to understand what happened today.

    FOLLOW (reader cares — block titles should convey what specifically happened):
    {follow_policy}

    TRASH — assign to the TRASH block:
    {trash_policy}

    For everything else, merge aggressively. "EU trade tensions with US escalate:
    15% tariffs announced, trade agreement suspended, retaliatory measures
    discussed" — that's 4 headlines in one block. Good compression.

    Prefer adding to existing blocks over creating new ones. When adding,
    UPDATE the block title to reflect the fuller picture.

    Do NOT write any files. Print your output to stdout ONLY.
    No commentary — output ONLY assignments.

    Output format:
    BLOCK <N>: <updated 2-4 sentence title>
    ADD: <comma-separated new headline numbers>

    NEW BLOCK: <2-4 sentence title>
    <comma-separated new headline numbers>

    {existing_blocks}

    === NEW HEADLINES ===
    {headlines}
""")

ITERATIVE_REFACTOR_PROMPT_V2 = textwrap.dedent("""\
    You are a senior news editor reviewing the final block structure of a daily
    digest. The reader sees ONLY block titles to understand what happened today.

    Review blocks below. Fix problems:
    - Blocks too broad for a coherent 2-4 sentence summary — split them.
    - Blocks with <3 articles — merge into a related block.
    - Rewrite ALL titles as 2-4 sentence summaries of what happened.
    - Target: around {max_blocks} blocks total.

    GOOD: "Kosovo war-crimes verdict upheld. Belgrade condemns ruling, recalls
    ambassador. Pristina says justice served after 25 years"
    BAD: "Balkan Politics"

    Do NOT write any files. Print your output to stdout ONLY.
    Output the FINAL block structure. Every article number must appear exactly once.

    Output format:
    BLOCK: <2-4 sentence summary>
    <comma-separated article numbers>

    === CURRENT BLOCKS ===
    {blocks}
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_headlines(path: Path) -> list[str]:
    """Load headlines file, return list of 'N: headline' lines."""
    return [line.strip() for line in path.read_text("utf-8").splitlines() if line.strip()]


def _run_agent(
    agent: str,
    model: str,
    prompt: str,
    workdir: Path,
    timeout: int = 600,
) -> tuple[str, float, int]:
    """Run an agent with the given prompt; return (output_text, elapsed_sec, exit_code).

    Agents may write results to stdout or to a file in the workdir.
    We check for output files first, then fall back to stdout.
    """
    cfg = AGENTS[agent][model]
    cmd_parts = cfg["cmd"]
    prompt_arg = cfg["prompt_arg"]

    prompt_file = workdir / "prompt.txt"
    prompt_file.write_text(prompt, "utf-8")

    if agent == "codex":
        full_cmd = f'{cmd_parts} "Read your task from prompt.txt and execute it."'
    elif prompt_arg:
        full_cmd = f'{cmd_parts} {prompt_arg} "Read your task from prompt.txt and execute it."'
    else:
        full_cmd = f'{cmd_parts} "Read your task from prompt.txt and execute it."'

    stdout_path = workdir / "agent_stdout.log"
    stderr_path = workdir / "agent_stderr.log"

    files_before = set(workdir.iterdir())

    env = os.environ.copy()
    start = time.monotonic()

    with stdout_path.open("w") as out_f, stderr_path.open("w") as err_f:
        proc = subprocess.Popen(  # noqa: S603 - command comes from trusted static config
            shlex.split(full_cmd),
            cwd=workdir,
            stdout=out_f,
            stderr=err_f,
            env=env,
        )
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    elapsed = time.monotonic() - start

    output_text = _find_agent_output(workdir, files_before, stdout_path)
    return output_text, elapsed, proc.returncode or 0


_SKIP_FILES = {"prompt.txt", "agent_stdout.log", "agent_stderr.log"}


def _find_agent_output(workdir: Path, files_before: set[Path], stdout_path: Path) -> str:
    """Find agent output — prefer new files over stdout."""
    new_files = [
        f
        for f in workdir.iterdir()
        if f.is_file() and f not in files_before and f.name not in _SKIP_FILES
    ]
    if new_files:
        best = max(new_files, key=lambda f: f.stat().st_size)
        text = best.read_text("utf-8", errors="replace")
        if text.strip():
            print(f"    (agent wrote output to {best.name})")
            return text

    return stdout_path.read_text("utf-8", errors="replace")


def _parse_blocks(text: str) -> list[dict]:
    """Parse BLOCK output into [{title, articles: [int]}]."""
    blocks = []
    current_title = None
    current_articles: list[int] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = re.match(r"^BLOCK(?:\s+\d+)?:\s*(.+)$", line, re.IGNORECASE)
        if m:
            if current_title is not None:
                blocks.append({"title": current_title, "articles": current_articles})
            current_title = m.group(1).strip()
            current_articles = []
            continue

        nums = re.findall(r"\d+", line)
        if nums and current_title is not None:
            current_articles.extend(int(n) for n in nums)

    if current_title is not None:
        blocks.append({"title": current_title, "articles": current_articles})

    return blocks


def _parse_events(text: str) -> list[dict]:
    """Parse EVENT output into [{title, articles: [int]}]."""
    events = []
    current_title = None
    current_articles: list[int] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = re.match(r"^EVENT(?:\s+\d+)?:\s*(.+)$", line, re.IGNORECASE)
        if m:
            if current_title is not None:
                events.append({"title": current_title, "articles": current_articles})
            current_title = m.group(1).strip()
            current_articles = []
            continue

        nums = re.findall(r"\d+", line)
        if nums and current_title is not None:
            current_articles.extend(int(n) for n in nums)

    if current_title is not None:
        events.append({"title": current_title, "articles": current_articles})

    return events


def _parse_iterative_output(text: str, existing_blocks: list[dict]) -> list[dict]:
    """Parse iterative batch output — merges ADD instructions into existing blocks.

    Handles updated block titles (prompt asks agent to update titles when adding).
    """
    blocks = [{"title": b["title"], "articles": list(b["articles"])} for b in existing_blocks]
    block_by_idx = {i + 1: b for i, b in enumerate(blocks)}

    current_block = None
    is_new = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = re.match(r"^BLOCK\s+(\d+):\s*(.+)$", line, re.IGNORECASE)
        if m:
            idx = int(m.group(1))
            current_block = block_by_idx.get(idx)
            if current_block is not None:
                new_title = m.group(2).strip()
                if new_title:
                    current_block["title"] = new_title
            else:
                new_block = {"title": m.group(2).strip(), "articles": []}
                blocks.append(new_block)
                block_by_idx[idx] = new_block
                current_block = new_block
                is_new = True
                continue
            is_new = False
            continue

        m = re.match(r"^NEW\s+BLOCK:\s*(.+)$", line, re.IGNORECASE)
        if m:
            new_block: dict = {"title": m.group(1).strip(), "articles": []}
            blocks.append(new_block)
            current_block = new_block
            is_new = True
            continue

        m = re.match(r"^ADD:\s*(.+)$", line, re.IGNORECASE)
        if m and current_block is not None:
            nums = re.findall(r"\d+", m.group(1))
            current_block["articles"].extend(int(n) for n in nums)
            continue

        if is_new and current_block is not None:
            nums = re.findall(r"\d+", line)
            if nums:
                current_block["articles"].extend(int(n) for n in nums)

    return blocks


def _compute_metrics(
    blocks: list[dict],
    total_headlines: int,
    elapsed: float,
) -> dict:
    """Compute automatic metrics from parsed blocks."""
    sizes = [len(b["articles"]) for b in blocks]
    all_assigned = set()
    for b in blocks:
        all_assigned.update(b["articles"])

    coverage = len(all_assigned) / total_headlines if total_headlines else 0
    duplicates = sum(len(b["articles"]) for b in blocks) - len(all_assigned)

    return {
        "block_count": len(blocks),
        "total_headlines": total_headlines,
        "coverage_pct": round(coverage * 100, 1),
        "assigned_count": len(all_assigned),
        "missing_count": total_headlines - len(all_assigned),
        "duplicate_assignments": duplicates,
        "size_min": min(sizes) if sizes else 0,
        "size_max": max(sizes) if sizes else 0,
        "size_median": sorted(sizes)[len(sizes) // 2] if sizes else 0,
        "size_mean": round(sum(sizes) / len(sizes), 1) if sizes else 0,
        "giant_blocks_gt30": sum(1 for size in sizes if size > _GIANT_BLOCK_SIZE),
        "singletons": sum(1 for s in sizes if s == 1),
        "wall_clock_seconds": round(elapsed, 1),
    }


def _format_existing_blocks(blocks: list[dict]) -> str:
    """Format blocks for iterative prompt context."""
    if not blocks:
        return "EXISTING BLOCKS: (none yet)"
    parts = ["EXISTING BLOCKS:"]
    for i, b in enumerate(blocks, 1):
        art_str = ", ".join(str(a) for a in b["articles"][:_BLOCK_ARTICLE_PREVIEW])
        if len(b["articles"]) > _BLOCK_ARTICLE_PREVIEW:
            art_str += ", ..."
        parts.append(f"BLOCK {i}: {b['title']} ({len(b['articles'])} articles: {art_str})")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Approaches
# ---------------------------------------------------------------------------


def run_single_pass(
    headlines: list[str],
    agent: str,
    model: str,
    workdir: Path,
    timeout: int,
) -> tuple[list[dict], float, str]:
    """Run single-pass grouping."""
    prompt = SINGLE_PASS_PROMPT.format(headlines="\n".join(headlines))
    stdout, elapsed, exit_code = _run_agent(agent, model, prompt, workdir, timeout)
    if exit_code != 0:
        print(f"  WARNING: agent exited with code {exit_code}", file=sys.stderr)
    blocks = _parse_blocks(stdout)
    return blocks, elapsed, stdout


def run_two_stage(
    headlines: list[str],
    agent: str,
    model: str,
    workdir: Path,
    timeout: int,
) -> tuple[list[dict], float, str]:
    """Run two-stage grouping (events → blocks)."""
    # Stage 1: headlines → events
    stage1_dir = workdir / "stage1_events"
    stage1_dir.mkdir(parents=True, exist_ok=True)
    prompt1 = TWO_STAGE_EVENTS_PROMPT.format(headlines="\n".join(headlines))
    stdout1, elapsed1, exit1 = _run_agent(agent, model, prompt1, stage1_dir, timeout)
    if exit1 != 0:
        print(f"  WARNING: stage1 agent exited with code {exit1}", file=sys.stderr)

    events = _parse_events(stdout1)
    print(f"  Stage 1: {len(events)} events in {elapsed1:.1f}s")

    # Stage 2: events → blocks
    events_text = "\n".join(f"{i}: {e['title']}" for i, e in enumerate(events, 1))
    stage2_dir = workdir / "stage2_blocks"
    stage2_dir.mkdir(parents=True, exist_ok=True)
    prompt2 = TWO_STAGE_BLOCKS_PROMPT.format(events=events_text)
    stdout2, elapsed2, exit2 = _run_agent(agent, model, prompt2, stage2_dir, timeout)
    if exit2 != 0:
        print(f"  WARNING: stage2 agent exited with code {exit2}", file=sys.stderr)

    event_blocks = _parse_blocks(stdout2)

    # Expand event numbers back to article numbers
    final_blocks = []
    for eb in event_blocks:
        articles = []
        for event_num in eb["articles"]:
            if 1 <= event_num <= len(events):
                articles.extend(events[event_num - 1]["articles"])
        final_blocks.append({"title": eb["title"], "articles": articles})

    total_elapsed = elapsed1 + elapsed2
    full_stdout = f"=== STAGE 1: EVENTS ===\n{stdout1}\n\n=== STAGE 2: BLOCKS ===\n{stdout2}"
    return final_blocks, total_elapsed, full_stdout


_BATCH_PROMPTS = {
    "A": ITERATIVE_BATCH_PROMPT_A,
    "B": ITERATIVE_BATCH_PROMPT_B,
}


def run_iterative(  # noqa: PLR0913
    headlines: list[str],
    agent: str,
    model: str,
    workdir: Path,
    timeout: int,
    batch_size: int,
    *,
    prompt_variant: str = "A",
    max_blocks: int = 25,
    follow_policy: str = "(none)",
    trash_policy: str = "(none)",
) -> tuple[list[dict], float, str]:
    """Run iterative grouping with batches + final refactor."""
    batch_template = _BATCH_PROMPTS.get(prompt_variant, ITERATIVE_BATCH_PROMPT_A)
    blocks: list[dict] = []
    total_elapsed = 0.0
    all_stdout_parts: list[str] = []
    batches = [headlines[i : i + batch_size] for i in range(0, len(headlines), batch_size)]

    for batch_idx, batch in enumerate(batches, 1):
        batch_dir = workdir / f"batch_{batch_idx}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        existing_text = _format_existing_blocks(blocks)
        prompt = batch_template.format(
            existing_blocks=existing_text,
            headlines="\n".join(batch),
            max_blocks=max_blocks,
            follow_policy=follow_policy,
            trash_policy=trash_policy,
        )

        stdout, elapsed, exit_code = _run_agent(agent, model, prompt, batch_dir, timeout)
        if exit_code != 0:
            print(
                f"  WARNING: batch {batch_idx} agent exited with code {exit_code}",
                file=sys.stderr,
            )

        blocks = _parse_iterative_output(stdout, blocks)
        total_elapsed += elapsed
        all_stdout_parts.append(f"=== BATCH {batch_idx} ({len(batch)} headlines) ===\n{stdout}")
        print(f"  Batch {batch_idx}/{len(batches)}: {len(blocks)} blocks, {elapsed:.1f}s")

    # Final refactor pass
    refactor_dir = workdir / "refactor"
    refactor_dir.mkdir(parents=True, exist_ok=True)
    blocks_text = "\n".join(
        f"BLOCK {i}: {b['title']}\n{', '.join(str(a) for a in b['articles'])}"
        for i, b in enumerate(blocks, 1)
    )
    refactor_prompt = ITERATIVE_REFACTOR_PROMPT_V2.format(
        blocks=blocks_text,
        max_blocks=max_blocks,
    )
    stdout_r, elapsed_r, exit_r = _run_agent(agent, model, refactor_prompt, refactor_dir, timeout)
    if exit_r != 0:
        print(f"  WARNING: refactor agent exited with code {exit_r}", file=sys.stderr)

    final_blocks = _parse_blocks(stdout_r)
    if not final_blocks:
        print("  WARNING: refactor produced no blocks, using pre-refactor state", file=sys.stderr)
        final_blocks = blocks

    total_elapsed += elapsed_r
    all_stdout_parts.append(f"=== REFACTOR PASS ===\n{stdout_r}")
    print(f"  Refactor: {len(final_blocks)} blocks, {elapsed_r:.1f}s")

    return final_blocks, total_elapsed, "\n\n".join(all_stdout_parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


_DEFAULT_FOLLOW = "Ukraine conflict, Balkan politics, EU economy"
_DEFAULT_TRASH = "Celebrity gossip, horoscopes, sponsored content"


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser(description="Grouping experiment runner")
    parser.add_argument(
        "--approach",
        required=True,
        choices=["single-pass", "two-stage", "iterative"],
    )
    parser.add_argument("--agent", required=True, choices=["gemini", "claude", "codex"])
    parser.add_argument("--model", required=True, help="Model tier or specific model name")
    parser.add_argument("--dataset", required=True, type=Path, help="Path to headlines .txt file")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size (iterative only)")
    parser.add_argument("--tag", required=True, help="Unique experiment tag for output directory")
    parser.add_argument("--timeout", type=int, default=600, help="Per-agent-call timeout (sec)")
    parser.add_argument(
        "--prompt-variant",
        default="A",
        choices=["A", "B"],
        help="Prompt variant for iterative approach",
    )
    parser.add_argument("--max-blocks", type=int, default=25, help="Target block count")
    parser.add_argument("--follow", default=_DEFAULT_FOLLOW, help="Follow policy topics")
    parser.add_argument("--trash", default=_DEFAULT_TRASH, help="Trash policy topics")
    args = parser.parse_args()

    if args.model not in AGENTS.get(args.agent, {}):
        valid = ", ".join(AGENTS.get(args.agent, {}).keys())
        parser.error(f"Unknown model '{args.model}' for agent '{args.agent}'. Valid: {valid}")

    headlines = _load_headlines(args.dataset)
    total = len(headlines)
    print(f"Experiment: {args.tag}")
    print(f"  Approach: {args.approach}")
    print(f"  Agent: {args.agent} ({args.model})")
    print(f"  Headlines: {total}")
    if args.approach == "iterative":
        print(f"  Batch size: {args.batch_size}")
        print(f"  Prompt variant: {args.prompt_variant}")
        print(f"  Max blocks: {args.max_blocks}")
        print(f"  Follow: {args.follow}")
        print(f"  Trash: {args.trash}")
    print()

    output_dir = _PROJECT_ROOT / "docs" / "reports" / "grouping" / args.tag
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    workdir = output_dir / "workdir"
    workdir.mkdir()

    config = {
        "approach": args.approach,
        "agent": args.agent,
        "model": args.model,
        "dataset": str(args.dataset),
        "dataset_size": total,
        "batch_size": args.batch_size if args.approach == "iterative" else None,
        "prompt_variant": args.prompt_variant if args.approach == "iterative" else None,
        "max_blocks": args.max_blocks if args.approach == "iterative" else None,
        "follow_policy": args.follow if args.approach == "iterative" else None,
        "trash_policy": args.trash if args.approach == "iterative" else None,
        "tag": args.tag,
        "timeout": args.timeout,
    }
    (output_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", "utf-8")

    if args.approach == "single-pass":
        blocks, elapsed, stdout = run_single_pass(
            headlines,
            args.agent,
            args.model,
            workdir,
            args.timeout,
        )
    elif args.approach == "two-stage":
        blocks, elapsed, stdout = run_two_stage(
            headlines,
            args.agent,
            args.model,
            workdir,
            args.timeout,
        )
    elif args.approach == "iterative":
        blocks, elapsed, stdout = run_iterative(
            headlines,
            args.agent,
            args.model,
            workdir,
            args.timeout,
            args.batch_size,
            prompt_variant=args.prompt_variant,
            max_blocks=args.max_blocks,
            follow_policy=args.follow,
            trash_policy=args.trash,
        )
    else:
        raise ValueError(f"Unknown approach: {args.approach}")

    (output_dir / "agent_stdout.log").write_text(stdout, "utf-8")
    (output_dir / "blocks.json").write_text(
        json.dumps(blocks, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )

    metrics = _compute_metrics(blocks, total, elapsed)
    metrics["approach"] = args.approach
    metrics["agent"] = args.agent
    metrics["model_tier"] = args.model
    metrics["prompt_variant"] = getattr(args, "prompt_variant", None)
    metrics["tag"] = args.tag
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", "utf-8")

    print()
    print(f"Results saved to: {output_dir}")
    print(f"  Blocks: {metrics['block_count']}")
    print(f"  Coverage: {metrics['coverage_pct']}%")
    print(f"  Missing: {metrics['missing_count']}")
    print(f"  Duplicates: {metrics['duplicate_assignments']}")
    print(
        f"  Sizes: min={metrics['size_min']} max={metrics['size_max']} "
        f"median={metrics['size_median']} mean={metrics['size_mean']}",
    )
    print(f"  Giants (>30): {metrics['giant_blocks_gt30']}")
    print(f"  Singletons: {metrics['singletons']}")
    print(f"  Time: {metrics['wall_clock_seconds']}s")


if __name__ == "__main__":
    main()
