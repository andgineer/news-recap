#!/usr/bin/env python3
"""Compare enrich strategies: separate files vs inline prompt.

Usage:
    python3 scripts/experiment_enrich_inline.py \
        --articles-dir scripts/datasets/enrich_sample --n 10 --agent codex-low
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import textwrap
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SEPARATOR = "═" * 72

AGENTS = {
    "codex-low": {
        "cmd": (
            "codex exec --sandbox workspace-write"
            " -c sandbox_workspace_write.network_access=true"
            " --model gpt-5.6-luna -c model_reasoning_effort=low"
        ),
        "vendor": "codex",
    },
    "codex-medium": {
        "cmd": (
            "codex exec --sandbox workspace-write"
            " -c sandbox_workspace_write.network_access=true"
            " --model gpt-5.6-terra -c model_reasoning_effort=low"
        ),
        "vendor": "codex",
    },
}

ENRICH_INSTRUCTIONS = textwrap.dedent("""\
    You are a senior news editor. Your job is to turn raw articles into \
    clear, informative pieces that respect the reader's time.

    For each article:
    1. Read and understand the full story — what happened, who is involved, \
    where, when, and why it matters.
    2. Write a headline that captures the essence of the story so the reader \
    gets maximum information without opening the article. Be specific and \
    factual — no clickbait, no vague teasers.
    3. Distill the article into a concise, self-contained excerpt (1-3 paragraphs). \
    Keep every key fact — names, numbers, locations, dates — but cut filler, \
    repetition, and promotional language.

    Write the headline and excerpt in the same language as the original article.
    Do not install packages or run web searches.\
""")

PROMPT_FILES = textwrap.dedent("""\
    {instructions}

    The directory input/articles/ contains numbered text files (1.txt, 2.txt, ...).
    Each file has: first line is the headline, then a blank line, then the article text.

    For each input file, create a file with the same name in output/articles/.
    Each output file must have the same format: first line is the new headline, \
    then a blank line, then the excerpt.

    Read and write files directly.\
""")

PROMPT_INLINE = textwrap.dedent("""\
    {instructions}

    Below are {n} articles. Each article starts with a line "### ARTICLE N ###" \
    (where N is the sequential number), followed by the headline on the next line, \
    then a blank line, then the article body.

    For each article, create a file output/articles/N.txt (matching the article number).
    Each output file must have: first line is the new headline, \
    then a blank line, then the excerpt.

    {articles_block}\
""")


def _run_agent(
    agent_key: str,
    prompt: str,
    workdir: Path,
    timeout: int = 300,
) -> tuple[float, int]:
    cfg = AGENTS[agent_key]
    prompt_file = workdir / "prompt.txt"
    prompt_file.write_text(prompt, "utf-8")

    full_cmd = f'{cfg["cmd"]} "Read your task from prompt.txt and execute it."'

    stdout_path = workdir / "agent_stdout.log"
    stderr_path = workdir / "agent_stderr.log"

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
            time.sleep(3)

    elapsed = time.monotonic() - start
    return elapsed, proc.returncode or 0


def _build_inline_block(article_files: list[Path]) -> str:
    parts: list[str] = []
    for i, src in enumerate(article_files, 1):
        text = src.read_text("utf-8").strip()
        parts.append(f"### ARTICLE {i} ###\n{text}")
    return "\n\n".join(parts)


def _collect_outputs(out_dir: Path, n: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        p = out_dir / f"{i}.txt"
        if not p.exists():
            results.append({"num": i, "ok": False})
            continue
        raw = p.read_text("utf-8", errors="replace").strip()
        blank = raw.find("\n\n")
        if blank > 0:
            title = raw[:blank].strip()[:200]
            excerpt_len = len(raw[blank + 2 :])
        else:
            title = raw[:200]
            excerpt_len = 0
        results.append({"num": i, "ok": True, "title": title, "excerpt_chars": excerpt_len})
    return results


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser(description="Enrich: files vs inline prompt")
    parser.add_argument("--articles-dir", required=True, type=Path)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--agent", default="codex-low", choices=list(AGENTS))
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    article_files = sorted(args.articles_dir.glob("*.txt"))[: args.n]
    n = len(article_files)
    print(f"Enrich inline experiment: {n} articles, agent={args.agent}", flush=True)

    out_root = _PROJECT_ROOT / ".news_recap_workdir" / "enrich-inline-exp"
    if out_root.exists():
        shutil.rmtree(out_root)

    # --- A: FILES ---
    print("\n  [A] FILES mode ...", flush=True)
    wd_a = out_root / "files"
    input_a = wd_a / "input" / "articles"
    output_a = wd_a / "output" / "articles"
    input_a.mkdir(parents=True)
    output_a.mkdir(parents=True)
    for i, src in enumerate(article_files, 1):
        shutil.copy2(src, input_a / f"{i}.txt")

    prompt_a = PROMPT_FILES.format(instructions=ENRICH_INSTRUCTIONS)
    elapsed_a, exit_a = _run_agent(args.agent, prompt_a, wd_a, args.timeout)
    results_a = _collect_outputs(output_a, n)
    ok_a = sum(1 for r in results_a if r["ok"])
    print(f"  [A] FILES: {ok_a}/{n} articles, {elapsed_a:.1f}s, exit={exit_a}", flush=True)

    # --- B: INLINE ---
    print("\n  [B] INLINE mode ...", flush=True)
    wd_b = out_root / "inline"
    output_b = wd_b / "output" / "articles"
    output_b.mkdir(parents=True)

    articles_block = _build_inline_block(article_files)
    prompt_b = PROMPT_INLINE.format(
        instructions=ENRICH_INSTRUCTIONS,
        n=n,
        articles_block=articles_block,
    )
    elapsed_b, exit_b = _run_agent(args.agent, prompt_b, wd_b, args.timeout)
    results_b = _collect_outputs(output_b, n)
    ok_b = sum(1 for r in results_b if r["ok"])
    print(f"  [B] INLINE: {ok_b}/{n} articles, {elapsed_b:.1f}s, exit={exit_b}", flush=True)

    # --- Summary ---
    print(f"\n{'=' * 80}", flush=True)
    print(f"{'Mode':<10} {'Time':>7} {'Output':>8} {'Prompt KB':>10}", flush=True)
    print("-" * 40, flush=True)
    prompt_a_kb = len(prompt_a.encode()) / 1024
    prompt_b_kb = len(prompt_b.encode()) / 1024
    print(f"{'FILES':<10} {elapsed_a:>6.1f}s {ok_a:>5}/{n} {prompt_a_kb:>9.1f}", flush=True)
    print(f"{'INLINE':<10} {elapsed_b:>6.1f}s {ok_b:>5}/{n} {prompt_b_kb:>9.1f}", flush=True)
    speedup = elapsed_a / elapsed_b if elapsed_b > 0 else 0
    print(f"\nSpeedup: {speedup:.2f}x", flush=True)

    print("\n--- Title comparison (first 3) ---", flush=True)
    for i in range(min(3, n)):
        ra = results_a[i]
        rb = results_b[i]
        ta = ra.get("title", "MISSING")[:70]
        tb = rb.get("title", "MISSING")[:70]
        print(f"  #{i + 1} FILES:  {ta}", flush=True)
        print(f"  #{i + 1} INLINE: {tb}", flush=True)
        print(flush=True)

    summary = {
        "agent": args.agent,
        "n": n,
        "files": {
            "elapsed": round(elapsed_a, 1),
            "ok": ok_a,
            "exit": exit_a,
            "prompt_kb": round(prompt_a_kb, 1),
            "articles": results_a,
        },
        "inline": {
            "elapsed": round(elapsed_b, 1),
            "ok": ok_b,
            "exit": exit_b,
            "prompt_kb": round(prompt_b_kb, 1),
            "articles": results_b,
        },
    }
    (out_root / "results.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )


if __name__ == "__main__":
    main()
