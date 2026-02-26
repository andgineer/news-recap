"""Task launcher: REDUCE phase — merge overlapping MAP blocks.

Reads block titles from MAP output, asks the LLM to merge overlapping
blocks, and produces BLOCK / SPLIT actions.  BLOCK actions are applied
in code (concatenate article lists); SPLIT actions are queued for the
separate SPLIT phase.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.models import DigestBlock
from news_recap.recap.storage.pipeline_io import materialize_step
from news_recap.recap.tasks.base import RecapPipelineError, TaskLauncher
from news_recap.recap.tasks.prompts import RECAP_REDUCE_PROMPT

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReduceAction:
    """One BLOCK or SPLIT action parsed from the reduce agent stdout."""

    kind: str  # "block" or "split"
    title: str
    source_indices: list[int] = field(default_factory=list)


@dataclass(slots=True)
class SplitTask:
    """A block that needs splitting — passed to the SPLIT phase."""

    title: str
    article_ids: list[str]


def _build_article_headline_map(
    ctx_state: dict[str, Any],
    ctx_article_map: dict[str, Any],
) -> dict[str, str]:
    """Build article_id -> headline lookup from context state."""
    enriched: dict[str, str] = ctx_state.get("enriched_articles", {})
    headline_map: dict[str, str] = {}
    for aid, entry in ctx_article_map.items():
        new_title = enriched.get(aid)
        if new_title:
            headline_map[aid] = new_title
        else:
            headline_map[aid] = entry.title
    return headline_map


def build_reduce_prompt(map_blocks: list[dict[str, Any]]) -> str:
    """Build the REDUCE prompt with numbered block titles and article counts."""
    lines = []
    for i, block in enumerate(map_blocks, 1):
        title = block["title"]
        n = len(block["article_ids"])
        lines.append(f"{i}: {title} ({n} articles)")
    return RECAP_REDUCE_PROMPT.format(block_titles="\n".join(lines))


def parse_reduce_stdout(
    stdout_path: Path,
    n_blocks: int,
) -> list[ReduceAction]:
    """Parse BLOCK/SPLIT lines from reduce agent stdout.

    Returns a list of ``ReduceAction`` objects.  Validates that every
    source block number (1..n_blocks) appears in exactly one action.
    Omitted blocks are treated as implicit single-block BLOCK with their
    original index.
    """
    if not stdout_path.exists():
        raise RecapPipelineError(
            "recap_reduce",
            f"REDUCE stdout not found: {stdout_path}",
        )

    text = stdout_path.read_text("utf-8").strip()
    if not text:
        raise RecapPipelineError("recap_reduce", "REDUCE stdout is empty")

    actions: list[ReduceAction] = []
    seen: set[int] = set()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(("BLOCK:", "SPLIT:")):
            kind = "block" if line.startswith("BLOCK:") else "split"
            title = line.split(":", 1)[1].strip()
            nums_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            nums = _parse_numbers(nums_line)
            deduped = [n for n in nums if n not in seen]
            dups = [n for n in nums if n in seen]
            if dups:
                logger.warning("REDUCE: duplicate source blocks ignored: %s", dups)
            if deduped:
                actions.append(
                    ReduceAction(kind=kind, title=title, source_indices=deduped),
                )
                seen.update(deduped)
            else:
                logger.warning("No source block numbers after %s line: %s", kind.upper(), title)
            i += 2
        else:
            i += 1

    if not actions:
        raise RecapPipelineError("recap_reduce", "REDUCE stdout has no valid BLOCK/SPLIT lines")

    missing = set(range(1, n_blocks + 1)) - seen
    if missing:
        logger.warning(
            "REDUCE: %d block(s) omitted by agent, treating as unchanged: %s",
            len(missing),
            sorted(missing),
        )
        for m in sorted(missing):
            actions.append(ReduceAction(kind="block", title="", source_indices=[m]))

    return actions


def _parse_numbers(line: str) -> list[int]:
    """Parse comma-separated integers from a line."""
    nums = []
    for part in line.split(","):
        token = part.strip()
        if token.isdigit():
            nums.append(int(token))
    return nums


def apply_reduce_plan(
    map_blocks: list[dict[str, Any]],
    actions: list[ReduceAction],
) -> tuple[list[DigestBlock], list[SplitTask]]:
    """Apply BLOCK/SPLIT actions to MAP blocks.

    Returns ``(final_blocks, split_tasks)``.  BLOCK actions produce
    ``DigestBlock`` objects directly.  SPLIT actions produce
    ``SplitTask`` objects for the SPLIT phase.
    """
    final_blocks: list[DigestBlock] = []
    split_tasks: list[SplitTask] = []

    for action in actions:
        merged_ids: list[str] = []
        for idx in action.source_indices:
            if 1 <= idx <= len(map_blocks):
                merged_ids.extend(map_blocks[idx - 1]["article_ids"])

        merged_ids = list(dict.fromkeys(merged_ids))

        if not merged_ids:
            continue

        title = action.title
        if not title and len(action.source_indices) == 1:
            title = map_blocks[action.source_indices[0] - 1]["title"]

        if action.kind == "block":
            final_blocks.append(DigestBlock(title=title, article_ids=merged_ids))
        else:
            split_tasks.append(SplitTask(title=title, article_ids=merged_ids))

    return final_blocks, split_tasks


_SPLIT_TASKS_FILENAME = "split_tasks.json"


def _save_split_tasks(pdir: Path, tasks: list[SplitTask]) -> None:
    """Persist split tasks to a JSON file so they survive pipeline restarts."""
    data = [{"title": t.title, "article_ids": t.article_ids} for t in tasks]
    (pdir / _SPLIT_TASKS_FILENAME).write_text(json.dumps(data), "utf-8")


def _load_split_tasks(pdir: Path) -> list[SplitTask]:
    """Load persisted split tasks, returning empty list if absent."""
    path = pdir / _SPLIT_TASKS_FILENAME
    if not path.exists():
        return []
    data = json.loads(path.read_text("utf-8"))
    return [SplitTask(title=d["title"], article_ids=d["article_ids"]) for d in data]


class ReduceBlocks(TaskLauncher):
    """Merge overlapping MAP blocks via inline prompt + stdout output."""

    name = "reduce_blocks"

    def restore_state(self) -> None:
        """Reconstruct ``split_tasks`` from persisted JSON for the SPLIT phase."""
        self.ctx.state["split_tasks"] = _load_split_tasks(self.ctx.pdir)

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()

        map_blocks: list[dict[str, Any]] = ctx.state.get("map_blocks", [])
        if not map_blocks:
            pf_logger.info("[reduce] No blocks to reduce")
            ctx.digest.blocks = []
            return

        prompt = build_reduce_prompt(map_blocks)

        tid = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_reduce",
            prompt=prompt,
        )

        pf_logger.info("[reduce] %d input blocks", len(map_blocks))

        tid = run_ai_agent.with_options(task_run_name=tid)(
            pipeline_dir=str(ctx.pdir),
            step_name="recap_reduce",
            task_id=tid,
        )

        stdout_path = ctx.pdir / tid / "output" / "agent_stdout.log"

        try:
            actions = parse_reduce_stdout(stdout_path, len(map_blocks))
        except RecapPipelineError:
            pf_logger.warning("[reduce] Failed to parse stdout — falling back to MAP blocks")
            ctx.digest.blocks = [
                DigestBlock(title=b["title"], article_ids=b["article_ids"]) for b in map_blocks
            ]
            return

        final_blocks, split_tasks = apply_reduce_plan(map_blocks, actions)

        if not final_blocks and not split_tasks:
            pf_logger.warning("[reduce] Empty reduce plan — falling back to MAP blocks")
            ctx.digest.blocks = [
                DigestBlock(title=b["title"], article_ids=b["article_ids"]) for b in map_blocks
            ]
            return

        ctx.digest.blocks = final_blocks
        ctx.state["split_tasks"] = split_tasks
        _save_split_tasks(ctx.pdir, split_tasks)

        n_block = sum(1 for a in actions if a.kind == "block")
        n_split = sum(1 for a in actions if a.kind == "split")
        pf_logger.info(
            "[reduce] %d BLOCK, %d SPLIT -> %d final blocks + %d to split",
            n_block,
            n_split,
            len(final_blocks),
            len(split_tasks),
        )
