"""Usage and answer files for Jev task workdirs (``<step>-jev``)."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

PRICE_PER_MTOK = 0.042
_USAGE_FILENAME = "meta/usage.json"
_ANSWERS_FILENAME = "output/jev_answers.json"


_DIR_SUFFIX = "-jev"


def jev_task_dir(pipeline_dir: Path, step: str) -> Path:
    """Return the workdir of a Jev step, listed in the stage table as ``<step>-jev``."""
    return pipeline_dir / f"{step}{_DIR_SUFFIX}"


def is_jev_task_dir(task_dir: Path) -> bool:
    return task_dir.name.endswith(_DIR_SUFFIX)


def save_jev_usage(
    task_dir: Path,
    *,
    elapsed: float,
    input_tokens: int,
    requests: int,
    model: str,
) -> None:
    """Add this run to ``meta/usage.json``, readable by ``read_agent_usage`` and the aggregator.

    A resumed night that asks Jev again is billed again, so earlier runs are kept in the sum.
    """
    path = task_dir / _USAGE_FILENAME
    previous: dict[str, Any] = {}
    if path.exists():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            previous = json.loads(path.read_text("utf-8"))
    tokens = int(previous.get("tokens_used") or 0) + input_tokens
    usage = {
        "elapsed_seconds": round(float(previous.get("elapsed_seconds") or 0) + elapsed, 1),
        "tokens_used": tokens,
        "total_tokens": tokens,
        "backend": "jev",
        "requests": int(previous.get("requests") or 0) + requests,
        "model": model,
        "cost_usd": round(tokens * PRICE_PER_MTOK / 1_000_000, 6),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage), "utf-8")


def save_answers(task_dir: Path, rows: list[dict[str, object]]) -> None:
    """Write per-item probabilities to ``output/jev_answers.json``."""
    path = task_dir / _ANSWERS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
