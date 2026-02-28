"""Task launcher: GROUP_SECTIONS phase — group blocks into reader-friendly sections.

Takes the flat list of ``DigestBlock`` objects produced by MAP/REDUCE/SPLIT
and asks an LLM to cluster them into sections with short topic labels.
When the block count is very small (<=3), the LLM call is skipped and all
blocks go into a single catch-all section.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
    run_single_agent,
)
from news_recap.recap.tasks.prompts import RECAP_GROUP_SECTIONS_PROMPT

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r"^SECTION:\s*(.+)$", re.IGNORECASE)
_MIN_BLOCKS_FOR_LLM = 4
_MAX_SECTION_BLOCKS = 10
_FALLBACK_TITLES = {"ru": "Все новости", "en": "All news"}


def build_group_sections_prompt(blocks: list[DigestBlock]) -> str:
    """Build the GROUP_SECTIONS prompt with numbered block titles."""
    lines = []
    for i, block in enumerate(blocks, 1):
        lines.append(f"{i}: {block.title}")
    return RECAP_GROUP_SECTIONS_PROMPT.format(
        block_count=len(blocks),
        blocks_listing="\n".join(lines),
    )


def parse_group_sections_stdout(
    stdout_path: Path,
    n_blocks: int,
) -> list[DigestSection]:
    """Parse ``SECTION:`` lines from group-sections agent stdout.

    Validates full block coverage and applies post-parse guardrails:
    - single-block sections are merged into the nearest neighbour
    - orphan blocks are appended to the last section
    """
    text = read_agent_stdout(stdout_path, "recap_group_sections").strip()

    raw_sections = _parse_section_lines(text, n_blocks)

    if not raw_sections:
        raise RecapPipelineError(
            "recap_group_sections",
            "GROUP_SECTIONS stdout has no valid SECTION lines",
        )

    raw_sections = _handle_orphans(raw_sections, n_blocks)
    raw_sections = _merge_single_block_sections(raw_sections)

    for section in raw_sections:
        if len(section.block_indices) > _MAX_SECTION_BLOCKS:
            logger.warning(
                "Section '%s' has %d blocks (exceeds soft cap of %d)",
                section.title,
                len(section.block_indices),
                _MAX_SECTION_BLOCKS,
            )

    return raw_sections


def _parse_section_lines(
    text: str,
    n_blocks: int,
) -> list[DigestSection]:
    """Extract SECTION: header + comma-separated numbers from text."""
    valid_nums = {str(i) for i in range(1, n_blocks + 1)}
    sections: list[DigestSection] = []
    seen: set[int] = set()
    current_title: str | None = None
    current_indices: list[int] = []

    def _flush() -> None:
        nonlocal current_title, current_indices
        if current_title and current_indices:
            sections.append(
                DigestSection(title=current_title, block_indices=current_indices),
            )
        current_title = None
        current_indices = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _SECTION_RE.match(line)
        if m:
            _flush()
            current_title = m.group(1).strip()
            continue
        if current_title is not None:
            nums = [t.strip() for t in re.split(r"[,\s]+", line) if t.strip()]
            for n in nums:
                if n in valid_nums and int(n) not in seen:
                    idx = int(n) - 1
                    current_indices.append(idx)
                    seen.add(int(n))

    _flush()
    return sections


def _handle_orphans(
    sections: list[DigestSection],
    n_blocks: int,
) -> list[DigestSection]:
    """Append any unassigned block indices to the last section."""
    assigned = {idx for s in sections for idx in s.block_indices}
    orphans = [i for i in range(n_blocks) if i not in assigned]
    if orphans and sections:
        sections[-1].block_indices.extend(orphans)
        logger.warning(
            "GROUP_SECTIONS: %d orphan block(s) appended to last section",
            len(orphans),
        )
    return sections


def _merge_single_block_sections(
    sections: list[DigestSection],
) -> list[DigestSection]:
    """Merge any section with only 1 block into its nearest neighbour."""
    if len(sections) <= 1:
        return sections

    merged: list[DigestSection] = []
    pending_singles: list[DigestSection] = []

    for section in sections:
        if len(section.block_indices) == 1:
            pending_singles.append(section)
        else:
            if pending_singles:
                for single in pending_singles:
                    section.block_indices.extend(single.block_indices)
                    logger.warning(
                        "Merged single-block section '%s' into '%s'",
                        single.title,
                        section.title,
                    )
                pending_singles = []
            merged.append(section)

    if pending_singles and merged:
        for single in pending_singles:
            merged[-1].block_indices.extend(single.block_indices)
            logger.warning(
                "Merged single-block section '%s' into '%s'",
                single.title,
                merged[-1].title,
            )
    elif pending_singles and not merged:
        combined_indices = [idx for s in pending_singles for idx in s.block_indices]
        merged.append(
            DigestSection(title=pending_singles[0].title, block_indices=combined_indices),
        )

    return merged


def _build_fallback_sections(
    blocks: list[DigestBlock],
    language: str,
) -> list[DigestSection]:
    """Create a single catch-all section for small block counts."""
    title = _FALLBACK_TITLES.get(language, _FALLBACK_TITLES["en"])
    return [DigestSection(title=title, block_indices=list(range(len(blocks))))]


class GroupSections(TaskLauncher):
    """Group blocks into reader-friendly sections with short topic labels."""

    name = "group_sections"

    def execute(self) -> None:
        ctx = self.ctx
        blocks = ctx.digest.blocks

        if not blocks:
            logger.info("[group_sections] No blocks to group")
            ctx.digest.recaps = []
            return

        if len(blocks) <= _MIN_BLOCKS_FOR_LLM - 1:
            logger.info(
                "[group_sections] Only %d block(s) — using fallback section",
                len(blocks),
            )
            ctx.digest.recaps = _build_fallback_sections(
                blocks,
                ctx.inp.preferences.language,
            )
            return

        prompt = build_group_sections_prompt(blocks)
        stdout_path = run_single_agent(ctx, "recap_group_sections", prompt)
        try:
            ctx.digest.recaps = parse_group_sections_stdout(stdout_path, len(blocks))
        except RecapPipelineError:
            logger.warning(
                "[group_sections] Failed to parse stdout — falling back to single section",
            )
            ctx.digest.recaps = _build_fallback_sections(
                blocks,
                ctx.inp.preferences.language,
            )

        logger.info(
            "[group_sections] %d blocks -> %d sections",
            len(blocks),
            len(ctx.digest.recaps),
        )
