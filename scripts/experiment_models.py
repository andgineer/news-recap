#!/usr/bin/env python3
"""Test all vendor models on classify and enrich tasks.

Usage:
    python3 scripts/experiment_models.py classify \
        --dataset scripts/datasets/full.txt --n 100 --tag "cls-test"

    python3 scripts/experiment_models.py enrich \
        --articles-dir /path/to/loaded/articles --n 10 --tag "enr-test"
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MIN_AGREEMENT_AGENTS = 2

AGENTS = {
    "gemini-pro": {
        "cmd": "gemini --model gemini-3.1-pro-preview --approval-mode auto_edit",
        "prompt_arg": "--prompt",
        "vendor": "gemini",
    },
    "gemini-flash": {
        "cmd": "gemini --model gemini-3.7-flash --approval-mode auto_edit",
        "prompt_arg": "--prompt",
        "vendor": "gemini",
    },
    "gemini-flash-lite": {
        "cmd": "gemini --model gemini-3.5-flash-lite --approval-mode auto_edit",
        "prompt_arg": "--prompt",
        "vendor": "gemini",
    },
    "codex-low": {
        "cmd": (
            "codex exec --sandbox workspace-write"
            " -c sandbox_workspace_write.network_access=true"
            " --model gpt-5.6-luna -c model_reasoning_effort=low"
        ),
        "prompt_arg": "",
        "vendor": "codex",
    },
    "codex-medium": {
        "cmd": (
            "codex exec --sandbox workspace-write"
            " -c sandbox_workspace_write.network_access=true"
            " --model gpt-5.6-terra -c model_reasoning_effort=low"
        ),
        "prompt_arg": "",
        "vendor": "codex",
    },
    "codex-high": {
        "cmd": (
            "codex exec --sandbox workspace-write"
            " -c sandbox_workspace_write.network_access=true"
            " --model gpt-5.6-sol -c model_reasoning_effort=low"
        ),
        "prompt_arg": "",
        "vendor": "codex",
    },
    "claude-sonnet": {
        "cmd": "claude -p --model claude-sonnet-5 --effort low --permission-mode dontAsk",
        "prompt_arg": "--",
        "vendor": "claude",
    },
}

_DEFAULT_FOLLOW = "Ukraine conflict, Balkan politics, EU economy"
_DEFAULT_TRASH = "Celebrity gossip, horoscopes, sponsored content"

CLASSIFY_PROMPT = textwrap.dedent("""\
    You are a news editor deciding which headlines to keep for a daily digest.

    EDITORIAL POLICY — TRASH:
    {trash_policy}

    EDITORIAL POLICY — FOLLOW:
    {follow_policy}

    These are topic descriptions, not keyword lists. A headline may relate to a
    described category even without sharing any exact words with the description.

    For each headline below, decide:
    1. Story matches a TRASH category → trash
    2. Story matches a FOLLOW topic → follow
    3. Headline too vague to identify the specific story → vague
    4. Otherwise → ok

    Do NOT write any scripts, use any tools, or read any files.
    Read the headlines below and print your verdicts directly to stdout.

    Print EXACTLY {expected_count} lines to stdout,
    one per headline, in the same order as the list below.
    Format: NUMBER: VERDICT  (VERDICT is one of: ok, vague, follow, trash)

    Example output (4 headlines):
    1: ok
    2: trash
    3: vague
    4: follow

    === HEADLINES (format: NUMBER: HEADLINE) ===
    {headlines_block}
""")

ENRICH_PROMPT = textwrap.dedent("""\
    You are a senior news editor. Your job is to turn raw articles into \
    clear, informative pieces that respect the reader's time.

    The directory input/articles/ contains numbered text files (1.txt, 2.txt, ...).
    Each file has: first line is the headline, then a blank line, then the article text.

    For each input file, create a file with the same name in output/articles/.
    Each output file must have the same format: first line is the new headline, \
    then a blank line, then the excerpt.

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

    Read and write files directly. Do not install packages or run web searches.
""")


def _run_agent(
    agent_key: str,
    prompt: str,
    workdir: Path,
    timeout: int = 300,
) -> tuple[str, float, int]:
    cfg = AGENTS[agent_key]
    cmd_parts = cfg["cmd"]
    prompt_arg = cfg["prompt_arg"]

    prompt_file = workdir / "prompt.txt"
    prompt_file.write_text(prompt, "utf-8")

    if cfg["vendor"] == "codex":
        full_cmd = f'{cmd_parts} "Read your task from prompt.txt and execute it."'
    elif prompt_arg:
        full_cmd = f'{cmd_parts} {prompt_arg} "Read your task from prompt.txt and execute it."'
    else:
        full_cmd = f'{cmd_parts} "Read your task from prompt.txt and execute it."'

    stdout_path = workdir / "agent_stdout.log"
    stderr_path = workdir / "agent_stderr.log"
    files_before = set(workdir.rglob("*"))

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

    elapsed = time.monotonic() - start

    new_files = [
        f
        for f in workdir.rglob("*")
        if f.is_file()
        and f not in files_before
        and f.name not in {"agent_stdout.log", "agent_stderr.log", "prompt.txt"}
        and f.suffix in (".txt", ".md", ".json")
    ]
    if new_files:
        biggest = max(new_files, key=lambda f: f.stat().st_size)
        output = biggest.read_text("utf-8", errors="replace")
    else:
        output = stdout_path.read_text("utf-8", errors="replace")

    return output, elapsed, proc.returncode or 0


# ---------------------------------------------------------------------------
# Classify experiment
# ---------------------------------------------------------------------------

_VALID_VERDICTS = {"ok", "vague", "follow", "trash"}


def _parse_classify_output(text: str, n: int) -> dict[int, str]:
    verdicts: dict[int, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for sep in (":", "\t"):
            if sep in line:
                parts = line.split(sep, 1)
                try:
                    num = int(parts[0].strip())
                except ValueError:
                    break
                verdict = parts[1].strip().lower()
                if verdict in _VALID_VERDICTS and 1 <= num <= n:
                    verdicts[num] = verdict
                break
    return verdicts


def run_classify(args: argparse.Namespace) -> None:
    headlines_all = [
        line.strip() for line in args.dataset.read_text("utf-8").splitlines() if line.strip()
    ]
    headlines = headlines_all[: args.n]
    n = len(headlines)

    print(f"Classify experiment: {n} headlines, tag={args.tag}", flush=True)

    output_dir = _PROJECT_ROOT / "docs" / "reports" / "models" / args.tag
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    headlines_block = "\n".join(headlines)
    prompt = CLASSIFY_PROMPT.format(
        trash_policy=args.trash,
        follow_policy=args.follow,
        expected_count=n,
        headlines_block=headlines_block,
    )

    agents_to_test = args.agents.split(",") if args.agents else list(AGENTS.keys())

    results: dict[str, dict] = {}

    for agent_key in agents_to_test:
        if agent_key not in AGENTS:
            print(f"  SKIP unknown agent: {agent_key}", flush=True)
            continue

        print(f"\n  Running classify: {agent_key} ...", flush=True)
        workdir = output_dir / agent_key
        workdir.mkdir(parents=True)

        output, elapsed, exit_code = _run_agent(agent_key, prompt, workdir, args.timeout)

        if exit_code != 0:
            print(f"  {agent_key}: FAILED (exit={exit_code}, {elapsed:.1f}s)", flush=True)
            results[agent_key] = {
                "status": "failed",
                "exit_code": exit_code,
                "elapsed": round(elapsed, 1),
            }
            continue

        verdicts = _parse_classify_output(output, n)
        counts = dict.fromkeys(_VALID_VERDICTS, 0)
        for v in verdicts.values():
            counts[v] += 1

        recognition = len(verdicts) / n
        results[agent_key] = {
            "status": "ok",
            "elapsed": round(elapsed, 1),
            "recognized": len(verdicts),
            "total": n,
            "recognition_rate": round(recognition, 3),
            "counts": counts,
            "verdicts": {str(k): v for k, v in sorted(verdicts.items())},
        }
        print(
            f"  {agent_key}: {len(verdicts)}/{n} parsed, {elapsed:.1f}s "
            f"| ok={counts['ok']} follow={counts['follow']} "
            f"vague={counts['vague']} trash={counts['trash']}",
            flush=True,
        )

    (output_dir / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )

    _print_classify_summary(agents_to_test, results)


def _print_classify_summary(agents: list[str], results: dict[str, dict]) -> None:
    print(f"\n{'=' * 80}", flush=True)
    print("Classify comparison:", flush=True)
    header = (
        f"{'Agent':<20} {'Time':>7} {'Parsed':>7} {'ok':>5} {'follow':>7} {'vague':>6} {'trash':>6}"
    )
    print(header, flush=True)
    print("-" * 70, flush=True)
    for agent_key in agents:
        r = results.get(agent_key)
        if not r or r["status"] == "failed":
            print(f"{agent_key:<20} {'FAIL':>7}", flush=True)
            continue
        c = r["counts"]
        print(
            f"{agent_key:<20} {r['elapsed']:>6.1f}s {r['recognized']:>5}/{r['total']} "
            f"{c['ok']:>5} {c['follow']:>7} {c['vague']:>6} {c['trash']:>6}",
            flush=True,
        )

    _print_agreement(results)


def _print_agreement(results: dict[str, dict]) -> None:
    ok_agents = [k for k, v in results.items() if v.get("status") == "ok"]
    if len(ok_agents) < _MIN_AGREEMENT_AGENTS:
        return

    print("\nVerdict agreement (% same verdict):", flush=True)
    for i, a1 in enumerate(ok_agents):
        for a2 in ok_agents[i + 1 :]:
            v1 = results[a1]["verdicts"]
            v2 = results[a2]["verdicts"]
            common = set(v1.keys()) & set(v2.keys())
            if not common:
                continue
            agree = sum(1 for k in common if v1[k] == v2[k])
            pct = agree / len(common) * 100
            print(f"  {a1} vs {a2}: {agree}/{len(common)} ({pct:.0f}%)", flush=True)


# ---------------------------------------------------------------------------
# Enrich experiment
# ---------------------------------------------------------------------------


def run_enrich(args: argparse.Namespace) -> None:  # noqa: C901
    articles_dir = Path(args.articles_dir)
    if not articles_dir.is_dir():
        print(f"ERROR: {articles_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    article_files = sorted(articles_dir.glob("*.txt"))[: args.n]
    n = len(article_files)

    print(f"Enrich experiment: {n} articles, tag={args.tag}", flush=True)

    output_dir = _PROJECT_ROOT / "docs" / "reports" / "models" / args.tag
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    agents_to_test = args.agents.split(",") if args.agents else list(AGENTS.keys())
    results: dict[str, dict] = {}

    for agent_key in agents_to_test:
        if agent_key not in AGENTS:
            print(f"  SKIP unknown agent: {agent_key}", flush=True)
            continue

        print(f"\n  Running enrich: {agent_key} ...", flush=True)
        workdir = output_dir / agent_key
        input_dir = workdir / "input" / "articles"
        out_articles = workdir / "output" / "articles"
        input_dir.mkdir(parents=True)
        out_articles.mkdir(parents=True)

        for i, src in enumerate(article_files, 1):
            shutil.copy2(src, input_dir / f"{i}.txt")

        output, elapsed, exit_code = _run_agent(
            agent_key,
            ENRICH_PROMPT,
            workdir,
            args.timeout,
        )

        if exit_code != 0:
            print(f"  {agent_key}: FAILED (exit={exit_code}, {elapsed:.1f}s)", flush=True)
            results[agent_key] = {
                "status": "failed",
                "exit_code": exit_code,
                "elapsed": round(elapsed, 1),
            }
            continue

        processed = list(out_articles.glob("*.txt"))
        examples = []
        for p in sorted(processed)[:3]:
            raw = p.read_text("utf-8", errors="replace").strip()
            blank = raw.find("\n\n")
            if blank > 0:
                examples.append(
                    {
                        "file": p.name,
                        "title": raw[:blank].strip()[:200],
                        "excerpt_chars": len(raw[blank + 2 :]),
                    },
                )

        results[agent_key] = {
            "status": "ok",
            "elapsed": round(elapsed, 1),
            "input_count": n,
            "output_count": len(processed),
            "examples": examples,
        }
        print(
            f"  {agent_key}: {len(processed)}/{n} articles, {elapsed:.1f}s",
            flush=True,
        )

    (output_dir / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )

    print(f"\n{'=' * 80}", flush=True)
    print("Enrich comparison:", flush=True)
    print(f"{'Agent':<20} {'Time':>7} {'Output':>8} {'Example title'}", flush=True)
    print("-" * 80, flush=True)
    for agent_key in agents_to_test:
        r = results.get(agent_key)
        if not r or r["status"] == "failed":
            print(f"{agent_key:<20} {'FAIL':>7}", flush=True)
            continue
        ex = r["examples"][0]["title"][:60] + "..." if r.get("examples") else "—"
        print(
            f"{agent_key:<20} {r['elapsed']:>6.1f}s {r['output_count']:>5}/{r['input_count']} {ex}",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Model comparison for classify/enrich")
    sub = parser.add_subparsers(dest="task", required=True)

    cls_p = sub.add_parser("classify")
    cls_p.add_argument("--dataset", required=True, type=Path)
    cls_p.add_argument("--n", type=int, default=100)
    cls_p.add_argument("--tag", required=True)
    cls_p.add_argument("--agents", default=None, help="Comma-separated agent keys")
    cls_p.add_argument("--timeout", type=int, default=300)
    cls_p.add_argument("--follow", default=_DEFAULT_FOLLOW)
    cls_p.add_argument("--trash", default=_DEFAULT_TRASH)

    enr_p = sub.add_parser("enrich")
    enr_p.add_argument("--articles-dir", required=True)
    enr_p.add_argument("--n", type=int, default=10)
    enr_p.add_argument("--tag", required=True)
    enr_p.add_argument("--agents", default=None, help="Comma-separated agent keys")
    enr_p.add_argument("--timeout", type=int, default=300)

    args = parser.parse_args()
    if args.task == "classify":
        run_classify(args)
    elif args.task == "enrich":
        run_enrich(args)


if __name__ == "__main__":
    main()
