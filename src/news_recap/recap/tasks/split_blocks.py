"""Task launcher: SPLIT phase — break broad blocks into thematic sub-blocks.

Runs only for blocks marked SPLIT by the REDUCE phase.  Each split
task is small (typically 5-20 articles) and runs as an independent
parallel agent via ``submit_and_collect``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from news_recap.recap.models import DigestBlock
from news_recap.recap.storage.pipeline_io import materialize_step, next_batch_number
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
)
from news_recap.recap.tasks.parallel import submit_and_collect
from news_recap.recap.tasks.prompts import RECAP_SPLIT_PROMPT
from news_recap.recap.tasks.reduce_blocks import SplitTask, _build_article_headline_map

logger = logging.getLogger(__name__)

_MAX_PARALLEL = 5
_MIN_COVERAGE = 0.50
_BLOCK_RE = re.compile(r"^BLOCK:\s*(.+)$", re.IGNORECASE)


def build_split_prompt(
    split_task: SplitTask,
    headline_map: dict[str, str],
) -> str:
    """Build the SPLIT prompt with numbered article headlines."""
    lines = []
    for i, aid in enumerate(split_task.article_ids, 1):
        headline = headline_map.get(aid, aid)
        lines.append(f"{i}: {headline}")
    return RECAP_SPLIT_PROMPT.format(articles_block="\n".join(lines))


def _parse_block_lines(
    text: str,
    valid_nums: set[str],
    num_to_id: dict[str, str],
) -> tuple[list[DigestBlock], set[str]]:
    """Parse ``BLOCK:`` / numbers sections, return blocks and seen number set."""
    blocks: list[DigestBlock] = []
    current_title: str | None = None
    current_ids: list[str] = []
    seen: set[str] = set()

    def _flush() -> None:
        nonlocal current_title, current_ids
        if current_title and current_ids:
            blocks.append(DigestBlock(title=current_title, article_ids=current_ids))
        current_title = None
        current_ids = []

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
                if n in valid_nums and n not in seen:
                    current_ids.append(num_to_id[n])
                    seen.add(n)
    _flush()
    return blocks, seen


def parse_split_stdout(
    stdout_path: Path,
    article_ids: list[str],
) -> list[DigestBlock]:
    """Parse BLOCK + numbers from split agent stdout.

    Maps sequential numbers back to article IDs using the same ordering
    that built the prompt.
    """
    text = read_agent_stdout(stdout_path, "recap_split").strip()

    valid_nums = {str(i + 1) for i in range(len(article_ids))}
    num_to_id = {str(i + 1): article_ids[i] for i in range(len(article_ids))}

    blocks, seen = _parse_block_lines(text, valid_nums, num_to_id)

    assigned = len(seen)
    total = len(article_ids)
    if total > 0 and assigned / total < _MIN_COVERAGE:
        raise RecapPipelineError(
            "recap_split",
            f"SPLIT coverage {assigned}/{total} ({assigned / total:.0%}) < {_MIN_COVERAGE:.0%}",
        )

    if assigned < total:
        unassigned = [num_to_id[str(i + 1)] for i in range(total) if str(i + 1) not in seen]
        if blocks:
            blocks[-1].article_ids.extend(unassigned)
            logger.warning(
                "SPLIT: %d unassigned articles appended to last block",
                len(unassigned),
            )
        else:
            blocks.append(DigestBlock(title="Uncategorized", article_ids=unassigned))

    return blocks


class SplitBlocks(TaskLauncher):
    """Break broad blocks into thematic sub-blocks via parallel LLM workers."""

    name = "split_blocks"

    def execute(self) -> None:
        ctx = self.ctx
        split_tasks: list[SplitTask] = ctx.state.get("split_tasks", [])
        if not split_tasks:
            logger.info("[split] No blocks to split")
            return

        headline_map = _build_article_headline_map(ctx.state, ctx.article_map)
        start_batch = next_batch_number(ctx.pdir, "recap_split") - 1

        def prepare_fn(item: SplitTask, batch_num: int) -> str:
            prompt = build_split_prompt(item, headline_map)
            return materialize_step(
                ctx.workdir_mgr,
                ctx.inp,
                step_name="recap_split",
                batch=batch_num,
                prompt=prompt,
            )

        def parse_fn(task_id: str, item: SplitTask, batch_num: int) -> list[DigestBlock]:  # noqa: ARG001
            stdout_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
            return parse_split_stdout(stdout_path, item.article_ids)

        logger.info("[split] %d blocks to split", len(split_tasks))

        results, n_failed, _ = submit_and_collect(
            ctx,
            split_tasks,
            step_name="recap_split",
            step_label="SPLIT worker",
            start_batch=start_batch,
            max_parallel=ctx.inp.effective_max_parallel(_MAX_PARALLEL),
            prepare_fn=prepare_fn,
            parse_fn=parse_fn,
            logger=logger,
        )

        new_blocks: list[DigestBlock] = []
        for block_list in results:
            new_blocks.extend(block_list)

        ctx.digest.blocks.extend(new_blocks)

        if n_failed > 0:
            self.fully_completed = False
            logger.error(
                "[split] %d/%d split tasks failed — partial results saved",
                n_failed,
                len(split_tasks),
            )
            raise RecapPipelineError(
                "recap_split",
                f"Worker failure: {n_failed}/{len(split_tasks)} splits failed",
            )

        logger.info(
            "[split] %d split tasks -> %d new blocks",
            len(split_tasks),
            len(new_blocks),
        )
