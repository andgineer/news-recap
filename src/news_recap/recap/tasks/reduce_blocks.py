"""Task launcher: REDUCE phase — merge overlapping blocks into final digest."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.models import DigestBlock
from news_recap.recap.storage.pipeline_io import materialize_step
from news_recap.recap.tasks.base import TaskLauncher
from news_recap.recap.tasks.prompts import RECAP_REDUCE_PROMPT

logger = logging.getLogger(__name__)


def _block_filename(block: dict[str, Any], index: int) -> str:
    worker = block.get("worker", 0)
    return f"w{worker}_b{index}.txt"


def build_block_index(map_blocks: list[dict[str, Any]]) -> str:
    """Build the inline block index text embedded in the REDUCE prompt."""
    return "\n".join(f"- {_block_filename(b, i)}: {b['title']}" for i, b in enumerate(map_blocks))


def write_block_files(
    workdir: Path,
    map_blocks: list[dict[str, Any]],
    article_map: dict[str, str],
) -> None:
    """Write block files to ``input/blocks/`` in the task workdir.

    *article_map* maps ``article_id → headline`` for annotation.
    Files are written directly (not via ``extra_input_files``) so paths
    in the REDUCE prompt match the actual filesystem layout.
    Also creates ``output/blocks/`` for agent output.
    """
    input_blocks = workdir / "input" / "blocks"
    input_blocks.mkdir(parents=True, exist_ok=True)
    (workdir / "output" / "blocks").mkdir(parents=True, exist_ok=True)

    for i, block in enumerate(map_blocks):
        filename = _block_filename(block, i)
        title = block["title"]
        lines = [title]
        for aid in block["article_ids"]:
            headline = article_map.get(aid, aid)
            lines.append(f"{aid}: {headline}")

        (input_blocks / filename).write_text("\n".join(lines) + "\n", "utf-8")


def _build_article_headline_map(
    ctx_state: dict[str, Any],
    ctx_article_map: dict[str, Any],
) -> dict[str, str]:
    """Build article_id → headline lookup from context state."""
    enriched: dict[str, dict[str, str]] = ctx_state.get("enriched_articles", {})
    headline_map: dict[str, str] = {}
    for aid, entry in ctx_article_map.items():
        enriched_data = enriched.get(aid)
        if enriched_data and enriched_data.get("new_title"):
            headline_map[aid] = enriched_data["new_title"]
        else:
            headline_map[aid] = entry.title
    return headline_map


def _parse_block_file(path: Path) -> DigestBlock | None:
    """Parse a single block ``.txt`` file, returning ``None`` on skip."""
    text = path.read_text("utf-8").strip()
    if not text:
        logger.warning("Empty block file: %s", path.name)
        return None

    lines = text.splitlines()
    title = lines[0].strip()
    if not title:
        logger.warning("Empty title in block file: %s", path.name)
        return None

    article_ids: list[str] = []
    for raw_line in lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        colon_pos = stripped.find(":")
        if colon_pos > 0:
            aid = stripped[:colon_pos].strip()
            if aid:
                article_ids.append(aid)
        else:
            article_ids.append(stripped)

    if not article_ids:
        logger.warning("No articles in block file: %s", path.name)
        return None
    return DigestBlock(title=title, article_ids=article_ids)


def parse_reduce_output(output_dir: Path) -> list[DigestBlock]:
    """Parse output/blocks/*.txt files into ``DigestBlock`` objects.

    Each file has: line 1 = block title, remaining lines = ``article_id: headline``.
    """
    if not output_dir.is_dir():
        logger.warning("REDUCE output dir not found: %s", output_dir)
        return []

    blocks: list[DigestBlock] = []
    for path in sorted(output_dir.iterdir()):
        if not path.name.endswith(".txt"):
            continue
        block = _parse_block_file(path)
        if block is not None:
            blocks.append(block)
    return blocks


class ReduceBlocks(TaskLauncher):
    """Merge overlapping MAP blocks into the final digest via a single LLM agent."""

    name = "reduce_blocks"

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()

        map_blocks: list[dict[str, Any]] = ctx.state.get("map_blocks", [])
        if not map_blocks:
            pf_logger.info("[reduce] No blocks to reduce")
            ctx.digest.blocks = []
            return

        headline_map = _build_article_headline_map(ctx.state, ctx.article_map)
        block_index = build_block_index(map_blocks)

        prompt = RECAP_REDUCE_PROMPT.format(block_index=block_index)

        tid = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_reduce",
            prompt=prompt,
        )

        write_block_files(ctx.pdir / tid, map_blocks, headline_map)

        pf_logger.info("[reduce] %d input blocks", len(map_blocks))

        tid = run_ai_agent.with_options(task_run_name=tid)(
            pipeline_dir=str(ctx.pdir),
            step_name="recap_reduce",
            task_id=tid,
        )

        output_dir = ctx.pdir / tid / "output" / "blocks"
        final_blocks = parse_reduce_output(output_dir)

        if not final_blocks:
            pf_logger.warning("[reduce] No output blocks parsed — falling back to MAP blocks")
            final_blocks = [
                DigestBlock(title=b["title"], article_ids=b["article_ids"]) for b in map_blocks
            ]

        ctx.digest.blocks = final_blocks
        pf_logger.info("[reduce] Final digest: %d blocks", len(final_blocks))
