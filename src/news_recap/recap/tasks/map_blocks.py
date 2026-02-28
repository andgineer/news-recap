"""Task launcher: MAP phase — group headlines into titled blocks via parallel LLM workers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import DigestBlock
from news_recap.recap.storage.pipeline_io import materialize_step, next_batch_number
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
)
from news_recap.recap.tasks.parallel import submit_and_collect
from news_recap.recap.tasks.prompts import RECAP_MAP_PROMPT

logger = logging.getLogger(__name__)

_MAX_PARALLEL = 3
_CHUNK_SIZE = 300
_MIN_COVERAGE = 0.50
_WARN_COVERAGE = 0.80
_BLOCK_RE = re.compile(r"^BLOCK:\s*(.+)$", re.IGNORECASE)


def merge_enriched_into_index(
    entries: list[ArticleIndexEntry],
    enriched: dict[str, str],
) -> list[ArticleIndexEntry]:
    """Update article titles from enrichment pass."""
    result: list[ArticleIndexEntry] = []
    for entry in entries:
        new_title = enriched.get(entry.source_id)
        if new_title:
            result.append(
                ArticleIndexEntry(
                    source_id=entry.source_id,
                    title=new_title,
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
) -> str:
    """Build the inline MAP prompt for a chunk of headlines."""
    headlines_block = "\n".join(f"{i + 1}: {e.title}" for i, e in enumerate(entries))
    return RECAP_MAP_PROMPT.format(
        follow_policy=follow_policy or "none",
        headline_count=len(entries),
        headlines_block=headlines_block,
    )


def _parse_blocks_from_text(
    text: str,
    valid_nums: set[str],
    num_to_id: dict[str, str],
    worker: int,
) -> list[dict[str, Any]]:
    """Parse ``BLOCK:``/numbers sections from raw MAP worker stdout."""
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
    return blocks


def _validate_map_blocks(
    blocks: list[dict[str, Any]],
    entries: list[ArticleIndexEntry],
    worker: int,
) -> list[dict[str, Any]]:
    """Check coverage, warn on duplicates, append uncategorized bucket."""
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
    text = read_agent_stdout(stdout_path, "recap_map")
    valid_nums = {str(i + 1) for i in range(len(entries))}
    num_to_id = {str(i + 1): entries[i].source_id for i in range(len(entries))}

    blocks = _parse_blocks_from_text(text, valid_nums, num_to_id, worker)
    return _validate_map_blocks(blocks, entries, worker)


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
        kept_entries: list[ArticleIndexEntry] = ctx.state["kept_entries"]
        enriched_articles: dict[str, str] = ctx.state.get("enriched_articles", {})
        entries = merge_enriched_into_index(kept_entries, enriched_articles)

        if not entries:
            logger.info("[map] No headlines to group")
            ctx.state["map_blocks"] = []
            return

        existing_blocks: list[dict[str, Any]] = []
        if ctx.digest.blocks:
            existing_blocks = [
                {"title": b.title, "article_ids": b.article_ids, "worker": 0}
                for b in ctx.digest.blocks
            ]
            covered_ids = {aid for b in existing_blocks for aid in b["article_ids"]}
            entries = [e for e in entries if e.source_id not in covered_ids]
            logger.info(
                "[map] Resuming: %d blocks from checkpoint, %d uncovered headlines remain",
                len(existing_blocks),
                len(entries),
            )
            if not entries:
                ctx.state["map_blocks"] = existing_blocks
                return

        chunks = split_into_map_chunks(entries)
        logger.info(
            "[map] %d headlines -> %d chunk(s)",
            len(entries),
            len(chunks),
        )

        follow_policy = ctx.inp.preferences.follow or "none"

        def prepare(chunk: list[ArticleIndexEntry], batch_num: int) -> str:
            prompt = build_map_prompt(chunk, follow_policy)
            task_id = materialize_step(
                ctx.workdir_mgr,
                ctx.inp,
                step_name="recap_map",
                batch=batch_num,
                prompt=prompt,
            )
            logger.info("[map] Worker %d — %d headlines", batch_num, len(chunk))
            return task_id

        def parse(task_id: str, chunk: list[ArticleIndexEntry], batch_num: int) -> list:
            stdout_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
            return parse_map_stdout(stdout_path, chunk, batch_num)

        batch_results, n_failed, _ = submit_and_collect(
            ctx,
            chunks,
            step_name="recap_map",
            step_label="map worker",
            start_batch=next_batch_number(ctx.pdir, "recap_map") - 1,
            max_parallel=ctx.inp.effective_max_parallel(_MAX_PARALLEL),
            prepare_fn=prepare,
            parse_fn=parse,
            logger=logger,
        )

        new_blocks = [block for worker_blocks in batch_results for block in worker_blocks]
        all_blocks = existing_blocks + new_blocks

        if not all_blocks:
            raise RecapPipelineError(
                "recap_map",
                "All workers produced zero blocks",
            )

        logger.info("[map] %d blocks from %d worker(s)", len(all_blocks), len(chunks))
        ctx.state["map_blocks"] = all_blocks
        ctx.digest.blocks = [
            DigestBlock(title=b["title"], article_ids=b["article_ids"]) for b in all_blocks
        ]

        if n_failed > 0:
            self.fully_completed = False
            raise RecapPipelineError(
                "recap_map",
                f"{n_failed} worker(s) failed"
                f" — {len(all_blocks)} blocks saved from successful workers",
            )
