#!/usr/bin/env python3
"""Map-Reduce experiment runner for grouping.

Usage:
    python scripts/experiment_mapreduce.py \
        --agent codex --model low \
        --dataset scripts/datasets/full.txt \
        --num-workers 3 --max-blocks 60 \
        --tag "mr-codex-low-w3"
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GIANT_BLOCK_SIZE = 30

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
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MAP_PROMPT = textwrap.dedent("""\
    You are a senior news editor. Compress these headlines into around {max_blocks}
    blocks for a daily digest.

    A block = a group of headlines that can be described in one informative title
    without mixing unrelated events. The title is 2-4 sentences telling the reader
    what happened. The reader sees ONLY titles to understand the day's news.

    GOOD block: "Heavy snow hits western Serbia, Valjevo road blocked, traffic
    disrupted across the region" — related events, one coherent picture.
    BAD block: "Snow in Serbia and 15 infants die in Sarajevo hospital" — unrelated
    events forced into one title.

    Merge aggressively when headlines belong together: "EU trade tensions with US
    escalate: 15% tariffs announced, trade agreement suspended, retaliatory measures
    discussed" — that's 4 headlines in one block. Good compression.

    FOLLOW (reader cares — block titles should convey what specifically happened):
    {follow_policy}

    TRASH — assign to the TRASH block:
    {trash_policy}

    Do NOT write any files. Print your output to stdout ONLY.
    No commentary — output ONLY the block structure.

    Output format:
    BLOCK: <2-4 sentence title>
    <comma-separated headline numbers>

    === HEADLINES ===
    {headlines}
""")

REDUCE_PROMPT = textwrap.dedent("""\
    You are a senior news editor. Several desks produced block lists independently.
    Review the combined block titles below and produce a unified block list.

    A block = a group of headlines that can be described in one informative title
    without mixing unrelated events.

    Rules:
    - Merge all blocks that overlap in topic. If the merged result fits one
      informative title — keep it as one block. If too broad — split into
      a smaller number of blocks, each with a clear title.
    - Remove duplicates.
    - Target: around {max_blocks} blocks total. Each title = 2-4 sentences.

    BLOCK TITLES:
    {block_index}

    After you decide the final block structure, update the article files
    accordingly. In input/blocks/ there is one file per block listed above.
    Each file has:
    - Line 1: block title
    - Remaining lines: article_id: headline

    Write the final blocks to output/blocks/ in the same format (title on line 1,
    then article_id: headline lines). Merged blocks = combined article lists
    with a new title. Split blocks = articles redistributed across new files.
    Unchanged blocks = copy as-is.
""")

_DEFAULT_FOLLOW = "Ukraine conflict, Balkan politics, EU economy"
_DEFAULT_TRASH = "Celebrity gossip, horoscopes, sponsored content"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_headlines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text("utf-8").splitlines() if line.strip()]


def _run_agent(
    agent: str,
    model: str,
    prompt: str,
    workdir: Path,
    timeout: int = 600,
) -> tuple[str, float, int]:
    """Run an agent; return (output_text, elapsed_sec, exit_code)."""
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
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            time.sleep(5)

    elapsed = time.monotonic() - start

    output_text = _find_agent_output(workdir, files_before, stdout_path)
    return output_text, elapsed, proc.returncode or 0


_SKIP_FILES = {"prompt.txt", "agent_stdout.log", "agent_stderr.log"}


def _find_agent_output(workdir: Path, files_before: set[Path], stdout_path: Path) -> str:
    new_files = [
        f
        for f in workdir.iterdir()
        if f.is_file()
        and f not in files_before
        and f.name not in _SKIP_FILES
        and f.suffix in (".txt", ".md", ".json")
    ]
    if new_files:
        biggest = max(new_files, key=lambda f: f.stat().st_size)
        return biggest.read_text("utf-8", errors="replace")
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


def _compute_metrics(blocks: list[dict], total_headlines: int, elapsed: float) -> dict:
    sizes = [len(b["articles"]) for b in blocks]
    all_assigned: set[int] = set()
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


# ---------------------------------------------------------------------------
# MAP phase
# ---------------------------------------------------------------------------


def _run_map_worker(  # noqa: PLR0913
    worker_id: int,
    headlines: list[str],
    agent: str,
    model: str,
    workdir: Path,
    timeout: int,
    max_blocks: int,
    follow_policy: str,
    trash_policy: str,
) -> tuple[int, list[dict], float, int]:
    """Run one MAP worker. Returns (worker_id, blocks, elapsed, exit_code)."""
    worker_dir = workdir / f"map_worker_{worker_id}"
    worker_dir.mkdir(parents=True, exist_ok=True)

    prompt = MAP_PROMPT.format(
        max_blocks=max_blocks,
        follow_policy=follow_policy,
        trash_policy=trash_policy,
        headlines="\n".join(headlines),
    )

    stdout, elapsed, exit_code = _run_agent(agent, model, prompt, worker_dir, timeout)
    if exit_code != 0:
        print(
            f"  WARNING: MAP worker {worker_id} exited with code {exit_code}",
            file=sys.stderr,
        )

    blocks = _parse_blocks(stdout)
    print(f"  MAP worker {worker_id}: {len(blocks)} blocks, {elapsed:.1f}s")
    return worker_id, blocks, elapsed, exit_code


def run_map_phase(  # noqa: PLR0913
    headlines: list[str],
    agent: str,
    model: str,
    workdir: Path,
    timeout: int,
    num_workers: int,
    max_blocks: int,
    follow_policy: str,
    trash_policy: str,
    sequential: bool = False,
) -> tuple[dict[int, list[dict]], float]:
    """Run MAP phase with parallel (or sequential) workers.

    Returns (worker_blocks, wall_clock_elapsed).
    worker_blocks maps worker_id -> list of blocks with GLOBAL article numbers.
    """
    chunk_size = math.ceil(len(headlines) / num_workers)
    chunks = []
    for i in range(num_workers):
        start_idx = i * chunk_size
        chunk = headlines[start_idx : start_idx + chunk_size]
        if chunk:
            chunks.append((i + 1, chunk))

    per_worker_blocks = max(max_blocks // len(chunks), 5)

    mode_label = "sequential" if sequential else "parallel"
    print(
        f"  MAP: {len(chunks)} workers ({mode_label}), ~{len(chunks[0][1])} headlines each, "
        f"target {per_worker_blocks} blocks/worker",
    )

    map_start = time.monotonic()
    worker_blocks: dict[int, list[dict]] = {}

    if sequential:
        for worker_id, chunk in chunks:
            completed_worker_id, blocks, elapsed, exit_code = _run_map_worker(
                worker_id,
                chunk,
                agent,
                model,
                workdir,
                timeout,
                per_worker_blocks,
                follow_policy,
                trash_policy,
            )
            worker_blocks[completed_worker_id] = blocks
    else:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(
                    _run_map_worker,
                    wid,
                    chunk,
                    agent,
                    model,
                    workdir,
                    timeout,
                    per_worker_blocks,
                    follow_policy,
                    trash_policy,
                ): wid
                for wid, chunk in chunks
            }
            for future in as_completed(futures):
                wid, blocks, elapsed, exit_code = future.result()
                worker_blocks[wid] = blocks

    map_elapsed = time.monotonic() - map_start
    total_blocks = sum(len(b) for b in worker_blocks.values())
    print(
        f"  MAP total: {total_blocks} blocks from {len(chunks)} workers, "
        f"{map_elapsed:.1f}s wall clock",
    )

    return worker_blocks, map_elapsed


# ---------------------------------------------------------------------------
# REDUCE phase
# ---------------------------------------------------------------------------


def _build_reduce_workdir(
    worker_blocks: dict[int, list[dict]],
    headlines: list[str],
    workdir: Path,
) -> tuple[Path, str]:
    """Create reduce workdir with block files and return (reduce_dir, block_index_text).

    Each block file: line 1 = title, remaining lines = article_id: headline text.
    """
    reduce_dir = workdir / "reduce"
    reduce_dir.mkdir(parents=True, exist_ok=True)
    input_blocks = reduce_dir / "input" / "blocks"
    input_blocks.mkdir(parents=True, exist_ok=True)
    output_blocks = reduce_dir / "output" / "blocks"
    output_blocks.mkdir(parents=True, exist_ok=True)

    headline_by_num: dict[int, str] = {}
    for h in headlines:
        m = re.match(r"^(\d+):\s*(.+)$", h)
        if m:
            headline_by_num[int(m.group(1))] = m.group(2).strip()

    index_lines: list[str] = []

    for wid in sorted(worker_blocks):
        for bidx, block in enumerate(worker_blocks[wid], 1):
            fname = f"w{wid}_b{bidx:02d}.txt"
            lines = [block["title"]]
            for art_id in block["articles"]:
                hl = headline_by_num.get(art_id, f"(headline {art_id})")
                lines.append(f"{art_id}: {hl}")
            (input_blocks / fname).write_text("\n".join(lines) + "\n", "utf-8")
            index_lines.append(f"{fname}: {block['title']}")

    block_index = "\n".join(index_lines)
    return reduce_dir, block_index


def _parse_reduce_output(reduce_dir: Path) -> list[dict]:
    """Parse output block files from reduce phase."""
    output_blocks = reduce_dir / "output" / "blocks"
    blocks = []

    if not output_blocks.exists():
        return blocks

    for fpath in sorted(output_blocks.iterdir()):
        if not fpath.is_file() or fpath.suffix not in (".txt", ".md"):
            continue
        lines = fpath.read_text("utf-8", errors="replace").splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        articles = []
        for line in lines[1:]:
            m = re.match(r"^(\d+):", line.strip())
            if m:
                articles.append(int(m.group(1)))
        if title:
            blocks.append({"title": title, "articles": articles})

    return blocks


def run_reduce_phase(  # noqa: PLR0913
    worker_blocks: dict[int, list[dict]],
    headlines: list[str],
    agent: str,
    model: str,
    workdir: Path,
    timeout: int,
    max_blocks: int,
) -> tuple[list[dict], float]:
    """Run REDUCE phase. Returns (final_blocks, elapsed)."""
    reduce_dir, block_index = _build_reduce_workdir(worker_blocks, headlines, workdir)

    prompt = REDUCE_PROMPT.format(
        max_blocks=max_blocks,
        block_index=block_index,
    )

    stdout, elapsed, exit_code = _run_agent(agent, model, prompt, reduce_dir, timeout)
    if exit_code != 0:
        print(f"  WARNING: REDUCE agent exited with code {exit_code}", file=sys.stderr)

    blocks = _parse_reduce_output(reduce_dir)

    if not blocks:
        print(
            "  WARNING: REDUCE produced no output files, falling back to stdout parsing",
            file=sys.stderr,
        )
        blocks = _parse_blocks(stdout)

    if not blocks:
        print(
            "  WARNING: REDUCE produced no blocks at all, using MAP output as-is",
            file=sys.stderr,
        )
        for wid in sorted(worker_blocks):
            blocks.extend(worker_blocks[wid])

    print(f"  REDUCE: {len(blocks)} blocks, {elapsed:.1f}s")
    return blocks, elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _print(*args: object, **kwargs: object) -> None:
    """Unbuffered print."""
    print(*args, **kwargs, flush=True)  # type: ignore[arg-type]


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser(description="Map-Reduce grouping experiment")
    parser.add_argument("--agent", required=True, choices=["gemini", "claude", "codex"])
    parser.add_argument("--model", required=True, help="Model tier")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--num-workers", type=int, default=3)
    parser.add_argument("--max-blocks", type=int, default=60)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--reduce-timeout", type=int, default=900)
    parser.add_argument(
        "--sequential-map",
        action="store_true",
        help="Run MAP workers sequentially (avoids rate limits)",
    )
    parser.add_argument("--follow", default=_DEFAULT_FOLLOW)
    parser.add_argument("--trash", default=_DEFAULT_TRASH)
    parser.add_argument(
        "--reduce-agent",
        default=None,
        help="Agent for reduce phase (defaults to same as map)",
    )
    parser.add_argument("--reduce-model", default=None)
    args = parser.parse_args()

    if args.model not in AGENTS.get(args.agent, {}):
        valid = ", ".join(AGENTS.get(args.agent, {}).keys())
        parser.error(f"Unknown model '{args.model}' for '{args.agent}'. Valid: {valid}")

    reduce_agent = args.reduce_agent or args.agent
    reduce_model = args.reduce_model or args.model
    if reduce_model not in AGENTS.get(reduce_agent, {}):
        valid = ", ".join(AGENTS.get(reduce_agent, {}).keys())
        parser.error(f"Unknown reduce model '{reduce_model}' for '{reduce_agent}'. Valid: {valid}")

    headlines = _load_headlines(args.dataset)
    total = len(headlines)

    print(f"Experiment: {args.tag}")
    print("  Approach: map-reduce")
    print(f"  MAP agent: {args.agent} ({args.model})")
    print(f"  REDUCE agent: {reduce_agent} ({reduce_model})")
    print(f"  Headlines: {total}")
    print(f"  Workers: {args.num_workers}")
    print(f"  Max blocks: {args.max_blocks}")
    print(f"  Follow: {args.follow}")
    print(f"  Trash: {args.trash}")
    print()

    output_dir = _PROJECT_ROOT / "docs" / "reports" / "grouping" / args.tag
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    work = output_dir / "workdir"
    work.mkdir()

    config = {
        "approach": "map-reduce",
        "map_agent": args.agent,
        "map_model": args.model,
        "reduce_agent": reduce_agent,
        "reduce_model": reduce_model,
        "dataset": str(args.dataset),
        "dataset_size": total,
        "num_workers": args.num_workers,
        "max_blocks": args.max_blocks,
        "follow_policy": args.follow,
        "trash_policy": args.trash,
        "tag": args.tag,
    }
    (output_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", "utf-8")

    # --- MAP ---
    worker_blocks, map_elapsed = run_map_phase(
        headlines,
        args.agent,
        args.model,
        work,
        args.timeout,
        args.num_workers,
        args.max_blocks,
        args.follow,
        args.trash,
        sequential=args.sequential_map,
    )

    map_blocks_flat = []
    for wid in sorted(worker_blocks):
        map_blocks_flat.extend(worker_blocks[wid])
    map_metrics = _compute_metrics(map_blocks_flat, total, map_elapsed)
    (output_dir / "map_metrics.json").write_text(
        json.dumps(map_metrics, indent=2) + "\n",
        "utf-8",
    )

    print(
        f"\n  MAP summary: {map_metrics['block_count']} blocks, "
        f"{map_metrics['coverage_pct']}% coverage, "
        f"{map_metrics['duplicate_assignments']} dups\n",
    )

    # --- REDUCE ---
    final_blocks, reduce_elapsed = run_reduce_phase(
        worker_blocks,
        headlines,
        reduce_agent,
        reduce_model,
        work,
        args.reduce_timeout,
        args.max_blocks,
    )

    total_elapsed = map_elapsed + reduce_elapsed

    (output_dir / "blocks.json").write_text(
        json.dumps(final_blocks, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )

    metrics = _compute_metrics(final_blocks, total, total_elapsed)
    metrics["approach"] = "map-reduce"
    metrics["map_agent"] = args.agent
    metrics["map_model"] = args.model
    metrics["reduce_agent"] = reduce_agent
    metrics["reduce_model"] = reduce_model
    metrics["map_elapsed"] = round(map_elapsed, 1)
    metrics["reduce_elapsed"] = round(reduce_elapsed, 1)
    metrics["num_workers"] = args.num_workers
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
    print(
        f"  Time: MAP={metrics['map_elapsed']}s REDUCE={metrics['reduce_elapsed']}s "
        f"total={metrics['wall_clock_seconds']}s",
    )


if __name__ == "__main__":
    main()
