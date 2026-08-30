#!/usr/bin/env python3
"""A/B test: does renaming "trash" to "exclude" reduce false positives?

Usage:
    python3 scripts/experiment_classify_label.py \
        --dataset scripts/datasets/full.txt --n 100
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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

AGENT_CMD = (
    "codex exec --sandbox workspace-write"
    " -c sandbox_workspace_write.network_access=true"
    " --model gpt-5.6-luna -c model_reasoning_effort=low"
)

_FOLLOW = "Ukraine conflict, Balkan politics, EU economy"
_UNWANTED = "Celebrity gossip, horoscopes, sponsored content"


def _make_prompt(*, label: str, n: int, headlines_block: str) -> str:
    """Build classify prompt with the given label name instead of 'trash'."""
    return textwrap.dedent(f"""\
        You are a news editor deciding which headlines to keep for a daily digest.

        EDITORIAL POLICY — {label.upper()}:
        {_UNWANTED}

        EDITORIAL POLICY — FOLLOW:
        {_FOLLOW}

        These are topic descriptions, not keyword lists. A headline may relate to a
        described category even without sharing any exact words with the description.

        For each headline below, decide:
        1. Story matches a {label.upper()} category → {label}
        2. Story matches a FOLLOW topic → follow
        3. Headline too vague to identify the specific story → vague
        4. Otherwise → ok

        Do NOT write any scripts, use any tools, or read any files.
        Read the headlines below and print your verdicts directly to stdout.

        Print EXACTLY {n} lines to stdout,
        one per headline, in the same order as the list below.
        Format: NUMBER: VERDICT  (VERDICT is one of: ok, vague, follow, {label})

        Example output (4 headlines):
        1: ok
        2: {label}
        3: vague
        4: follow

        === HEADLINES (format: NUMBER: HEADLINE) ===
        {headlines_block}
    """)


def _run(prompt: str, workdir: Path, timeout: int = 300) -> tuple[str, float, int]:
    workdir.mkdir(parents=True, exist_ok=True)
    prompt_file = workdir / "prompt.txt"
    prompt_file.write_text(prompt, "utf-8")

    full_cmd = f'{AGENT_CMD} "Read your task from prompt.txt and execute it."'
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

    elapsed = time.monotonic() - start
    output = stdout_path.read_text("utf-8", errors="replace")
    return output, elapsed, proc.returncode or 0


def _parse(text: str, n: int, valid_labels: set[str]) -> dict[int, str]:
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
                if verdict in valid_labels and 1 <= num <= n:
                    verdicts[num] = verdict
                break
    return verdicts


def main() -> None:  # noqa: C901, PLR0915
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    headlines_all = [
        line.strip() for line in args.dataset.read_text("utf-8").splitlines() if line.strip()
    ]
    headlines = headlines_all[: args.n]
    n = len(headlines)
    headlines_block = "\n".join(headlines)

    out_root = _PROJECT_ROOT / ".news_recap_workdir" / "classify-label-exp"

    variants = ["trash", "exclude"]

    all_results: dict[str, dict] = {}

    for label in variants:
        print(f"\n  Running: label={label} ...", flush=True)
        workdir = out_root / label
        if workdir.exists():
            shutil.rmtree(workdir)

        prompt = _make_prompt(label=label, n=n, headlines_block=headlines_block)
        valid = {"ok", "vague", "follow", label}
        output, elapsed, exit_code = _run(prompt, workdir, args.timeout)

        if exit_code != 0:
            print(f"  {label}: FAILED (exit={exit_code}, {elapsed:.1f}s)", flush=True)
            all_results[label] = {"status": "failed"}
            continue

        verdicts = _parse(output, n, valid)
        counts = dict.fromkeys(("ok", "follow", "vague", label), 0)
        for v in verdicts.values():
            counts[v] = counts.get(v, 0) + 1

        all_results[label] = {
            "elapsed": round(elapsed, 1),
            "parsed": len(verdicts),
            "counts": counts,
            "verdicts": {str(k): v for k, v in sorted(verdicts.items())},
        }
        print(
            f"  {label}: {len(verdicts)}/{n} parsed, {elapsed:.1f}s | "
            + " ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            flush=True,
        )

    # --- Comparison ---
    print(f"\n{'=' * 70}", flush=True)
    print(
        f"{'Label':<10} {'Time':>7} {'ok':>5} {'follow':>7} {'vague':>6} {'unwanted':>9}",
        flush=True,
    )
    print("-" * 50, flush=True)
    for label in variants:
        r = all_results.get(label)
        if not r or r.get("status") == "failed":
            print(f"{label:<10} FAIL", flush=True)
            continue
        c = r["counts"]
        unwanted = c.get(label, 0)
        print(
            f"{label:<10} {r['elapsed']:>6.1f}s {c.get('ok', 0):>5} "
            f"{c.get('follow', 0):>7} {c.get('vague', 0):>6} {unwanted:>9}",
            flush=True,
        )

    # Agreement
    if all(all_results.get(label, {}).get("verdicts") for label in variants):
        v_trash = all_results["trash"]["verdicts"]
        v_exclude = all_results["exclude"]["verdicts"]
        common = set(v_trash) & set(v_exclude)
        same = 0
        diffs = []
        for k in sorted(common, key=int):
            vt = v_trash[k]
            ve = v_exclude[k]
            if vt == ve or (vt == "trash" and ve == "exclude"):
                same += 1
            else:
                diffs.append((k, vt, ve))
        print(f"\nAgreement: {same}/{len(common)} ({same / len(common) * 100:.0f}%)", flush=True)
        if diffs:
            print(f"\nDisagreements ({len(diffs)}):", flush=True)
            for num, vt, ve in diffs[:20]:
                hl = headlines[int(num) - 1][:80]
                print(f"  #{num}: trash→{vt}, exclude→{ve}  | {hl}", flush=True)

    (out_root / "results.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )


if __name__ == "__main__":
    main()
