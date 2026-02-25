"""Task launcher: MAP phase — group headlines into titled blocks via parallel LLM workers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.storage.pipeline_io import materialize_step, next_batch_number
from news_recap.recap.tasks.base import (
    FlowContext,
    PipelineStepResult,
    RecapPipelineError,
    TaskLauncher,
)
from news_recap.recap.tasks.prompts import RECAP_MAP_PROMPT

logger = logging.getLogger(__name__)

_MAX_PARALLEL = 3
_CHUNK_SIZE = 300
_MIN_COVERAGE = 0.50
_WARN_COVERAGE = 0.80
_MIN_BATCH_SUCCESS_RATE = 0.5
_BLOCK_RE = re.compile(r"^BLOCK:\s*(.+)$", re.IGNORECASE)


def merge_enriched_into_index(
    entries: list[ArticleIndexEntry],
    enriched: dict[str, dict[str, str]],
) -> list[ArticleIndexEntry]:
    """Update article titles from enrichment pass."""
    result: list[ArticleIndexEntry] = []
    for entry in entries:
        enriched_data = enriched.get(entry.source_id)
        if enriched_data and enriched_data.get("new_title"):
            result.append(
                ArticleIndexEntry(
                    source_id=entry.source_id,
                    title=enriched_data["new_title"],
                    url=entry.url,
                    source=entry.source,
                    published_at=entry.published_at,
                ),
            )
        else:
            result.append(entry)
    return result


def split_into_map_chunks(
    entries: list[ArticleIndexEntry],
) -> list[list[ArticleIndexEntry]]:
    """Split headline entries into roughly even chunks for parallel MAP workers.

    >>> from news_recap.recap.contracts import ArticleIndexEntry
    >>> entries = [
    ...     ArticleIndexEntry(source_id=str(i), title=f"T{i}", url="u",
    ...                       source="s", published_at="2026-01-01")
    ...     for i in range(10)
    ... ]
    >>> chunks = split_into_map_chunks(entries)
    >>> len(chunks) >= 1
    True
    """
    if not entries:
        return []
    n = len(entries)
    n_chunks = max(1, min(_MAX_PARALLEL, -(-n // _CHUNK_SIZE)))
    base, extra = divmod(n, n_chunks)
    chunks: list[list[ArticleIndexEntry]] = []
    start = 0
    for i in range(n_chunks):
        size = base + (1 if i < extra else 0)
        chunks.append(entries[start : start + size])
        start += size
    return chunks


def build_map_prompt(
    entries: list[ArticleIndexEntry],
    follow_policy: str,
    max_blocks: int,
) -> str:
    """Build the inline MAP prompt for a chunk of headlines."""
    headlines_block = "\n".join(f"{i + 1}: {e.title}" for i, e in enumerate(entries))
    return RECAP_MAP_PROMPT.format(
        max_blocks=max_blocks,
        follow_policy=follow_policy or "none",
        headlines_block=headlines_block,
    )


def parse_map_stdout(
    stdout_path: Path,
    entries: list[ArticleIndexEntry],
    worker: int,
) -> list[dict[str, Any]]:
    """Parse MAP worker stdout into blocks.

    Expected format::

        BLOCK: <title>
        1, 3, 5, 12

    Returns list of ``{"title": str, "article_ids": list[str], "worker": int}``.
    Raises ``RecapPipelineError`` if headline coverage drops below 50%.
    """
    if not stdout_path.exists():
        logger.warning("MAP stdout not found: %s — returning empty blocks", stdout_path)
        return []

    text = stdout_path.read_text("utf-8")
    valid_nums = {str(i + 1) for i in range(len(entries))}
    num_to_id = {str(i + 1): entries[i].source_id for i in range(len(entries))}

    blocks: list[dict[str, Any]] = []
    current_title: str | None = None
    current_nums: list[str] = []

    def _flush() -> None:
        nonlocal current_title, current_nums
        if current_title and current_nums:
            aids = [num_to_id[n] for n in current_nums if n in num_to_id]
            if aids:
                blocks.append({"title": current_title, "article_ids": aids, "worker": worker})
        current_title = None
        current_nums = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _BLOCK_RE.match(line)
        if m:
            _flush()
            current_title = m.group(1).strip()
            continue
        if current_title is not None:
            nums = [t.strip() for t in re.split(r"[,\s]+", line) if t.strip()]
            for n in nums:
                if n in valid_nums and n not in current_nums:
                    current_nums.append(n)
    _flush()

    assigned = {aid for b in blocks for aid in b["article_ids"]}
    all_ids = {e.source_id for e in entries}
    coverage = len(assigned) / len(entries) if entries else 1.0

    if coverage < _MIN_COVERAGE:
        raise RecapPipelineError(
            "recap_map",
            f"Worker {worker}: coverage {coverage:.0%} < {_MIN_COVERAGE:.0%} "
            f"({len(assigned)}/{len(entries)} headlines assigned)",
        )
    if coverage < _WARN_COVERAGE:
        logger.warning(
            "MAP worker %d: low coverage %.0f%% (%d/%d headlines)",
            worker,
            coverage * 100,
            len(assigned),
            len(entries),
        )

    dup_ids = set()
    seen: set[str] = set()
    for b in blocks:
        for aid in b["article_ids"]:
            if aid in seen:
                dup_ids.add(aid)
            seen.add(aid)
    if dup_ids:
        logger.warning(
            "MAP worker %d: %d headline(s) appear in multiple blocks",
            worker,
            len(dup_ids),
        )

    unassigned = all_ids - assigned
    if unassigned:
        uncat_ids = sorted(unassigned)
        blocks.append({"title": "Uncategorized", "article_ids": uncat_ids, "worker": worker})

    return blocks


class MapBlocks(TaskLauncher):
    """Group headlines into titled blocks via parallel MAP workers."""

    name = "map_blocks"

    def restore_state(self) -> None:
        """Reconstruct ``map_blocks`` from persisted digest blocks."""
        self.ctx.state["map_blocks"] = [
            {"title": b.title, "article_ids": b.article_ids, "worker": 0}
            for b in self.ctx.digest.blocks
        ]

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()

        kept_entries: list[ArticleIndexEntry] = ctx.state["kept_entries"]
        enriched_articles: dict[str, dict[str, str]] = ctx.state.get("enriched_articles", {})
        entries = merge_enriched_into_index(kept_entries, enriched_articles)

        if not entries:
            pf_logger.info("[map] No headlines to group")
            ctx.state["map_blocks"] = []
            return

        max_blocks = max(5, len(entries) // 15)
        chunks = split_into_map_chunks(entries)
        pf_logger.info(
            "[map] %d headlines -> %d chunk(s), target ~%d blocks",
            len(entries),
            len(chunks),
            max_blocks,
        )

        follow_policy = ctx.inp.preferences.follow or "none"
        per_chunk_blocks = max(5, max_blocks // len(chunks))

        all_blocks: list[dict[str, Any]] = []
        batch_counter = next_batch_number(ctx.pdir, "recap_map") - 1

        for window_start in range(0, len(chunks), _MAX_PARALLEL):
            window = chunks[window_start : window_start + _MAX_PARALLEL]

            futures: list[tuple[int, list[ArticleIndexEntry], Any]] = []
            for chunk in window:
                batch_counter += 1
                prompt = build_map_prompt(chunk, follow_policy, per_chunk_blocks)
                task_id = materialize_step(
                    ctx.workdir_mgr,
                    ctx.inp,
                    step_name="recap_map",
                    batch=batch_counter,
                    prompt=prompt,
                )
                pf_logger.info("[map] Worker %d — %d headlines", batch_counter, len(chunk))
                future = run_ai_agent.with_options(task_run_name=task_id).submit(
                    pipeline_dir=str(ctx.pdir),
                    step_name="recap_map",
                    task_id=task_id,
                )
                futures.append((batch_counter, chunk, future))

            for worker_num, chunk, future in futures:
                try:
                    tid = future.result()
                    stdout_path = ctx.pdir / tid / "output" / "agent_stdout.log"
                    worker_blocks = parse_map_stdout(stdout_path, chunk, worker_num)
                    all_blocks.extend(worker_blocks)
                    ctx.result.steps.append(
                        PipelineStepResult(f"map worker {worker_num}", tid, "completed"),
                    )
                except RecapPipelineError as exc:
                    pf_logger.error("MAP worker %d failed: %s", worker_num, exc)
                    ctx.result.steps.append(
                        PipelineStepResult(f"map worker {worker_num}", None, "failed"),
                    )

        failed_workers = sum(
            1 for s in ctx.result.steps if s.step_name.startswith("map worker") and s.status == "failed"
        )
        n_workers = len(chunks)
        if n_workers > 0 and (n_workers - failed_workers) / n_workers < _MIN_BATCH_SUCCESS_RATE:
            raise RecapPipelineError(
                "recap_map",
                f"Too many worker failures: {failed_workers}/{n_workers} failed",
            )

        if not all_blocks:
            raise RecapPipelineError(
                "recap_map",
                "All workers produced zero blocks",
            )

        pf_logger.info("[map] %d blocks from %d worker(s)", len(all_blocks), len(chunks))
        ctx.state["map_blocks"] = all_blocks
