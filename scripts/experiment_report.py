#!/usr/bin/env python3
"""Collect grouping experiment metrics into a comparison table.

Usage:
    python scripts/experiment_report.py
    python scripts/experiment_report.py --format csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPORTS_DIR = _PROJECT_ROOT / "docs" / "reports" / "grouping"

COLUMNS = [
    ("tag", 35),
    ("approach", 12),
    ("agent", 8),
    ("model_tier", 7),
    ("block_count", 6),
    ("coverage_pct", 8),
    ("missing_count", 7),
    ("duplicate_assignments", 5),
    ("size_min", 4),
    ("size_max", 4),
    ("size_median", 6),
    ("giant_blocks_gt30", 6),
    ("singletons", 5),
    ("wall_clock_seconds", 7),
]


def _collect_metrics() -> list[dict]:
    """Scan all experiment directories and collect metrics.json files."""
    results = []
    if not _REPORTS_DIR.is_dir():
        return results

    for tag_dir in sorted(_REPORTS_DIR.iterdir()):
        metrics_path = tag_dir / "metrics.json"
        if not metrics_path.is_file():
            continue
        try:
            data = json.loads(metrics_path.read_text("utf-8"))
            results.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: skipping {tag_dir.name}: {exc}", file=sys.stderr)

    return results


def _print_markdown(results: list[dict]) -> None:
    """Print comparison table in markdown format."""
    headers = [col for col, _ in COLUMNS]
    header_labels = {
        "tag": "Tag",
        "approach": "Approach",
        "agent": "Agent",
        "model_tier": "Model",
        "block_count": "Blocks",
        "coverage_pct": "Cov%",
        "missing_count": "Miss",
        "duplicate_assignments": "Dups",
        "size_min": "Min",
        "size_max": "Max",
        "size_median": "Med",
        "giant_blocks_gt30": ">30",
        "singletons": "×1",
        "wall_clock_seconds": "Time(s)",
    }

    widths = {col: max(w, len(header_labels.get(col, col))) for col, w in COLUMNS}
    for r in results:
        for col, _ in COLUMNS:
            val = str(r.get(col, ""))
            widths[col] = max(widths[col], len(val))

    header_line = " | ".join(header_labels.get(h, h).ljust(widths[h]) for h in headers)
    sep_line = " | ".join("-" * widths[h] for h in headers)
    print(f"| {header_line} |")
    print(f"| {sep_line} |")

    for r in results:
        row = " | ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers)
        print(f"| {row} |")


def _print_csv(results: list[dict]) -> None:
    """Print comparison table in CSV format."""
    headers = [col for col, _ in COLUMNS]
    print(",".join(headers))
    for r in results:
        print(",".join(str(r.get(h, "")) for h in headers))


def main() -> None:
    parser = argparse.ArgumentParser(description="Grouping experiment report")
    parser.add_argument("--format", choices=["markdown", "csv"], default="markdown")
    args = parser.parse_args()

    results = _collect_metrics()
    if not results:
        print("No experiment results found.", file=sys.stderr)
        print(f"Run experiments first, results expected in {_REPORTS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 80}")
    print(f"  Grouping Experiment Results ({len(results)} runs)")
    print(f"{'=' * 80}\n")

    if args.format == "csv":
        _print_csv(results)
    else:
        _print_markdown(results)

    print()


if __name__ == "__main__":
    main()
