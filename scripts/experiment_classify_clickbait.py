#!/usr/bin/env python3
"""A/B test: does adding clickbait detection to the classify prompt catch more teasers?

Usage:
    python3 scripts/experiment_classify_clickbait.py \
        --dataset scripts/datasets/clickbait-test.txt --n 500
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

_EXCLUDE_POLICY = "horoscopes, medical advice, sports (except Russia), Epstein files"

_VAGUE_RULES: dict[str, str] = {
    "control": "Headline too vague to identify the specific story → vague",
    "treatment-a": (
        "Headline is vague or clickbait — key facts are hidden behind teasers, "
        "rhetorical questions, or deliberate omissions → vague"
    ),
    "treatment-b": (
        "Headline is vague or clickbait — it hides key facts behind teasers, "
        'rhetorical questions, or deliberate omissions (e.g. "on a popular '
        'island…", "one trend…", "the secret of…", "expert revealed…") → vague'
    ),
}


def _make_prompt(*, vague_rule: str, n: int, headlines_block: str) -> str:
    return textwrap.dedent(f"""\
        You are a news editor deciding which headlines to keep for a daily digest.

        EDITORIAL POLICY — EXCLUDE:
        {_EXCLUDE_POLICY}

        These are topic descriptions, not keyword lists. A headline may relate to a
        described category even without sharing any exact words with the description.

        For each headline below, decide:
        1. Story matches an EXCLUDE category → exclude
        2. {vague_rule}
        3. Otherwise → ok

        Read the headlines below and provide your verdicts.

        Print EXACTLY {n} lines to stdout,
        one per headline, in the same order as the list below.
        Format: NUMBER: VERDICT  (VERDICT is one of: ok, vague, exclude)

        Example output (3 headlines):
        1: ok
        2: exclude
        3: vague

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


def _parse(text: str, n: int) -> dict[int, str]:
    valid_labels = {"ok", "vague", "exclude"}
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


def main() -> None:  # noqa: C901, PLR0912, PLR0915
    parser = argparse.ArgumentParser(
        description="A/B test classify prompt variants for clickbait detection",
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    headlines_all = [
        line.strip() for line in args.dataset.read_text("utf-8").splitlines() if line.strip()
    ]
    headlines = headlines_all[: args.n]
    n = len(headlines)
    headlines_block = "\n".join(f"{i + 1}: {h}" for i, h in enumerate(headlines))

    out_root = _PROJECT_ROOT / ".news_recap_workdir" / "classify-clickbait-exp"
    variants = list(_VAGUE_RULES.keys())
    all_results: dict[str, dict] = {}

    for variant in variants:
        print(f"\n  Running: {variant} ...", flush=True)
        workdir = out_root / variant
        if workdir.exists():
            shutil.rmtree(workdir)

        prompt = _make_prompt(
            vague_rule=_VAGUE_RULES[variant],
            n=n,
            headlines_block=headlines_block,
        )
        output, elapsed, exit_code = _run(prompt, workdir, args.timeout)

        if exit_code != 0:
            print(f"  {variant}: FAILED (exit={exit_code}, {elapsed:.1f}s)", flush=True)
            all_results[variant] = {"status": "failed"}
            continue

        verdicts = _parse(output, n)
        counts: dict[str, int] = {"ok": 0, "vague": 0, "exclude": 0}
        for v in verdicts.values():
            counts[v] = counts.get(v, 0) + 1

        all_results[variant] = {
            "elapsed": round(elapsed, 1),
            "parsed": len(verdicts),
            "counts": counts,
            "verdicts": {str(k): v for k, v in sorted(verdicts.items())},
        }
        print(
            f"  {variant}: {len(verdicts)}/{n} parsed, {elapsed:.1f}s | "
            + " ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            flush=True,
        )

    # --- Summary table ---
    print(f"\n{'=' * 70}", flush=True)
    print(f"{'Variant':<15} {'Time':>7} {'ok':>5} {'vague':>6} {'exclude':>8}", flush=True)
    print("-" * 50, flush=True)
    for variant in variants:
        r = all_results.get(variant)
        if not r or r.get("status") == "failed":
            print(f"{variant:<15} FAIL", flush=True)
            continue
        c = r["counts"]
        print(
            f"{variant:<15} {r['elapsed']:>6.1f}s {c.get('ok', 0):>5} "
            f"{c.get('vague', 0):>6} {c.get('exclude', 0):>8}",
            flush=True,
        )

    # --- Pairwise comparisons against control ---
    ctrl_verdicts = (all_results.get("control") or {}).get("verdicts")
    if not ctrl_verdicts:
        print("\nControl variant missing — cannot compute diffs.", flush=True)
    else:
        for variant in variants:
            if variant == "control":
                continue
            treat_verdicts = (all_results.get(variant) or {}).get("verdicts")
            if not treat_verdicts:
                continue

            print(f"\n--- {variant} vs control ---", flush=True)
            common = set(ctrl_verdicts) & set(treat_verdicts)
            same = 0
            ok_to_vague: list[tuple[str, str]] = []
            vague_to_ok: list[tuple[str, str]] = []
            other_diffs: list[tuple[str, str, str]] = []

            for k in sorted(common, key=int):
                num_key: str = str(k)
                vc = ctrl_verdicts[num_key]
                vt = treat_verdicts[num_key]
                if vc == vt:
                    same += 1
                elif vc == "ok" and vt == "vague":
                    ok_to_vague.append((num_key, headlines[int(num_key) - 1]))
                elif vc == "vague" and vt == "ok":
                    vague_to_ok.append((num_key, headlines[int(num_key) - 1]))
                else:
                    other_diffs.append((num_key, vc, vt))

            print(
                f"Agreement: {same}/{len(common)} ({same / len(common) * 100:.0f}%)",
                flush=True,
            )
            if ok_to_vague:
                print(f"\nFlipped ok→vague ({len(ok_to_vague)}) — expected wins:", flush=True)
                for num, hl in ok_to_vague:
                    print(f"  #{num}: {hl[:100]}", flush=True)
            if vague_to_ok:
                print(f"\nFlipped vague→ok ({len(vague_to_ok)}) — regressions:", flush=True)
                for num, hl in vague_to_ok:
                    print(f"  #{num}: {hl[:100]}", flush=True)
            if other_diffs:
                print(f"\nOther disagreements ({len(other_diffs)}):", flush=True)
                for num, vc, vt in other_diffs[:20]:
                    hl = headlines[int(num) - 1][:80]
                    print(f"  #{num}: control→{vc}, {variant}→{vt}  | {hl}", flush=True)

    (out_root / "results.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False) + "\n",
        "utf-8",
    )
    print(f"\nResults written to {out_root / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
