"""Task launcher: REDUCE phase — merge overlapping MAP blocks.

Reads block titles from MAP output, asks the LLM to merge overlapping
blocks, and produces BLOCK / SPLIT actions.  BLOCK actions are applied
in code (concatenate article lists); SPLIT actions are queued for the
separate SPLIT phase.

When the number of MAP blocks exceeds ``_REDUCE_CHUNK_LIMIT``, a
tree-reduce is used: blocks are chunked and reduced in parallel, then
the combined results are reduced once more.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from news_recap.recap.models import DigestBlock
from news_recap.recap.storage.pipeline_io import materialize_step, next_batch_number
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
    run_single_agent,
)
from news_recap.recap.tasks.parallel import submit_and_collect
from news_recap.recap.tasks.prompts import RECAP_REDUCE_PROMPT, PromptBackend, render_prompt

logger = logging.getLogger(__name__)

_REDUCE_CHUNK_LIMIT = 200
_FINAL_REDUCE_LIMIT = 200


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


def build_reduce_prompt(
    map_blocks: list[dict[str, Any]],
    backend: PromptBackend = PromptBackend.CLI,
) -> str:
    """Build the REDUCE prompt with numbered block titles and article counts."""
    lines: list[str] = []
    for i, block in enumerate(map_blocks, 1):
        title = block["title"]
        n = len(block["article_ids"])
        lines.append(f"{i}: {title} ({n} articles)")
    return render_prompt(RECAP_REDUCE_PROMPT, backend, block_titles="\n".join(lines))


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
    text = read_agent_stdout(stdout_path, "recap_reduce").strip()

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


def _run_single_reduce(
    ctx: Any,
    blocks: list[dict[str, Any]],
    *,
    batch: int | None = None,
) -> tuple[list[DigestBlock], list[SplitTask]]:
    """Execute one REDUCE call and return ``(final_blocks, split_tasks)``.

    On parse failure, raises ``RecapPipelineError``.
    """
    prompt = build_reduce_prompt(blocks, ctx.inp.prompt_backend)
    stdout_path = run_single_agent(ctx, "recap_reduce", prompt, batch=batch)
    actions = parse_reduce_stdout(stdout_path, len(blocks))
    return apply_reduce_plan(blocks, actions)


def _interleave_by_worker(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder blocks so that each consecutive run mixes different MAP workers.

    MAP workers produce non-overlapping blocks internally; overlaps only
    exist *between* workers.  Round-robin interleaving ensures each chunk
    fed to a REDUCE pass sees blocks from multiple workers, maximising
    duplicate detection.
    """
    by_worker: dict[int, list[dict[str, Any]]] = {}
    for b in blocks:
        w = b.get("worker", 0)
        by_worker.setdefault(w, []).append(b)

    if len(by_worker) <= 1:
        return blocks

    iterators = [iter(v) for v in by_worker.values()]
    result: list[dict[str, Any]] = []
    while iterators:
        remaining = []
        for it in iterators:
            val = next(it, None)
            if val is not None:
                result.append(val)
                remaining.append(it)
        iterators = remaining
    return result


def _chunk_blocks(
    blocks: list[dict[str, Any]],
    chunk_size: int,
) -> list[list[dict[str, Any]]]:
    """Split *blocks* into roughly-even chunks of at most *chunk_size*."""
    if not blocks:
        return []
    n_chunks = max(1, -(-len(blocks) // chunk_size))
    base, extra = divmod(len(blocks), n_chunks)
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    for i in range(n_chunks):
        size = base + (1 if i < extra else 0)
        chunks.append(blocks[start : start + size])
        start += size
    return chunks


def _blocks_to_dicts(
    blocks: list[DigestBlock],
    splits: list[SplitTask],
) -> list[dict[str, Any]]:
    """Convert REDUCE results back to dict format for a subsequent pass.

    A ``kind`` field (``"block"`` or ``"split"``) is preserved so that
    downstream code can reconstruct the correct types when the final
    REDUCE pass is skipped.
    """
    result: list[dict[str, Any]] = []
    for b in blocks:
        result.append({"title": b.title, "article_ids": b.article_ids, "kind": "block"})
    for s in splits:
        result.append({"title": s.title, "article_ids": s.article_ids, "kind": "split"})
    return result


def _split_intermediate(
    intermediate: list[dict[str, Any]],
) -> tuple[list[DigestBlock], list[SplitTask]]:
    """Reconstruct typed blocks/splits from intermediate dicts."""
    blocks: list[DigestBlock] = []
    splits: list[SplitTask] = []
    for b in intermediate:
        if b.get("kind") == "split":
            splits.append(SplitTask(title=b["title"], article_ids=b["article_ids"]))
        else:
            blocks.append(DigestBlock(title=b["title"], article_ids=b["article_ids"]))
    return blocks, splits


class ReduceBlocks(TaskLauncher):
    """Merge overlapping MAP blocks via inline prompt + stdout output.

    When the block count exceeds ``_REDUCE_CHUNK_LIMIT``, a two-level
    tree-reduce is used: blocks are chunked and reduced in parallel,
    then the combined results optionally go through a final pass.
    """

    name = "reduce_blocks"

    def restore_state(self) -> None:
        """Reconstruct ``split_tasks`` from persisted JSON for the SPLIT phase."""
        self.ctx.state["split_tasks"] = _load_split_tasks(self.ctx.pdir)

    def execute(self) -> None:
        ctx = self.ctx
        map_blocks: list[dict[str, Any]] = ctx.state.get("map_blocks", [])
        if not map_blocks:
            logger.info("[reduce] No blocks to reduce")
            ctx.digest.blocks = []
            return

        logger.info("[reduce] %d input blocks", len(map_blocks))

        if len(map_blocks) <= _REDUCE_CHUNK_LIMIT:
            final_blocks, split_tasks = self._single_reduce(map_blocks, logger)
        else:
            final_blocks, split_tasks = self._tree_reduce(map_blocks, logger)

        ctx.digest.blocks = final_blocks
        ctx.state["split_tasks"] = split_tasks
        _save_split_tasks(ctx.pdir, split_tasks)

        logger.info(
            "[reduce] result: %d blocks + %d to split",
            len(final_blocks),
            len(split_tasks),
        )

    def _single_reduce(
        self,
        map_blocks: list[dict[str, Any]],
        logger: Any,
    ) -> tuple[list[DigestBlock], list[SplitTask]]:
        """Single-pass REDUCE (original behavior).

        Agent errors (timeout, crash) propagate — no silent fallback.
        Only parse failures trigger a fallback to the original MAP blocks.
        """
        ctx = self.ctx
        prompt = build_reduce_prompt(map_blocks, ctx.inp.prompt_backend)

        try:
            stdout_path = run_single_agent(ctx, "recap_reduce", prompt)
            actions = parse_reduce_stdout(stdout_path, len(map_blocks))
            return apply_reduce_plan(map_blocks, actions)
        except RecapPipelineError:
            logger.warning("[reduce] Failed to parse stdout — falling back to MAP blocks")
            fallback = [
                DigestBlock(title=b["title"], article_ids=b["article_ids"]) for b in map_blocks
            ]
            return fallback, []

    def _tree_reduce(
        self,
        map_blocks: list[dict[str, Any]],
        logger: Any,
    ) -> tuple[list[DigestBlock], list[SplitTask]]:
        """Two-level tree-reduce for large block counts."""
        ctx = self.ctx
        interleaved = _interleave_by_worker(map_blocks)
        chunks = _chunk_blocks(interleaved, _REDUCE_CHUNK_LIMIT)
        logger.info(
            "[reduce] tree-reduce: %d blocks -> %d chunk(s) of ≤%d",
            len(map_blocks),
            len(chunks),
            _REDUCE_CHUNK_LIMIT,
        )

        def prepare(chunk: list[dict[str, Any]], batch_num: int) -> str:
            prompt = build_reduce_prompt(chunk, ctx.inp.prompt_backend)
            task_id = materialize_step(
                ctx.workdir_mgr,
                ctx.inp,
                step_name="recap_reduce",
                batch=batch_num,
                prompt=prompt,
            )
            logger.info("[reduce] pass-1 chunk %d — %d blocks", batch_num, len(chunk))
            return task_id

        def parse(
            task_id: str,
            chunk: list[dict[str, Any]],
            batch_num: int,
        ) -> list[dict[str, Any]]:
            stdout_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
            actions = parse_reduce_stdout(stdout_path, len(chunk))
            blocks, splits = apply_reduce_plan(chunk, actions)
            logger.info(
                "[reduce] pass-1 chunk %d: %d blocks + %d splits",
                batch_num,
                len(blocks),
                len(splits),
            )
            return _blocks_to_dicts(blocks, splits)

        chunk_results, n_failed, _ = submit_and_collect(
            ctx,
            chunks,
            step_name="recap_reduce",
            step_label="reduce chunk",
            start_batch=next_batch_number(ctx.pdir, "recap_reduce") - 1,
            max_parallel=ctx.inp.effective_max_parallel(len(chunks)),
            prepare_fn=prepare,
            parse_fn=parse,
            logger=logger,
        )

        intermediate = [b for chunk_blocks in chunk_results for b in chunk_blocks]
        logger.info("[reduce] pass-1 produced %d intermediate blocks", len(intermediate))

        if not intermediate:
            logger.warning("[reduce] pass-1 empty — falling back to MAP blocks")
            fallback = [
                DigestBlock(title=b["title"], article_ids=b["article_ids"]) for b in map_blocks
            ]
            return fallback, []

        final_blocks, split_tasks = self._finish_tree_reduce(
            ctx,
            intermediate,
            logger,
        )

        if n_failed > 0:
            self.fully_completed = False
            ctx.digest.blocks = final_blocks
            ctx.state["split_tasks"] = split_tasks
            _save_split_tasks(ctx.pdir, split_tasks)
            raise RecapPipelineError(
                "recap_reduce",
                f"Chunk failure(s) — {len(final_blocks)} blocks saved from successful chunks",
            )

        return final_blocks, split_tasks

    def _finish_tree_reduce(
        self,
        ctx: Any,
        intermediate: list[dict[str, Any]],
        logger: Any,
    ) -> tuple[list[DigestBlock], list[SplitTask]]:
        """Run final REDUCE pass or reconstruct typed results from pass-1."""
        if len(intermediate) <= _FINAL_REDUCE_LIMIT:
            logger.info("[reduce] final pass on %d blocks", len(intermediate))
            try:
                return _run_single_reduce(ctx, intermediate, batch=0)
            except RecapPipelineError:
                logger.warning("[reduce] final pass failed — using pass-1 results")
                return _split_intermediate(intermediate)

        logger.info(
            "[reduce] %d intermediate blocks > %d limit — skipping final pass",
            len(intermediate),
            _FINAL_REDUCE_LIMIT,
        )
        return _split_intermediate(intermediate)
