"""Task launcher: REFINE_LAYOUT phase — absorb small sections.

Oneshot-only post-processing step that runs after OneshotDigest.
A single LLM call receives section titles and block titles (no article IDs)
and may relocate blocks from small (1-2 block) sections into existing larger
sections where they are a clear semantic fit.  Larger sections, block list,
and article mappings are never modified.
"""

from __future__ import annotations

import logging
import re

from news_recap.recap.models import DigestSection, language_display_name
from news_recap.recap.tasks.base import (
    TaskLauncher,
    read_agent_stdout,
    run_single_agent,
)
from news_recap.recap.tasks.prompts import RECAP_REFINE_LAYOUT_PROMPT, render_prompt

logger = logging.getLogger(__name__)

_MIN_BLOCKS_PER_SECTION = 3  # sections with <= 2 blocks are "tiny"


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------


def needs_refinement(sections: list[DigestSection], n_blocks: int) -> bool:
    """Return True when any section has fewer than ``_MIN_BLOCKS_PER_SECTION`` blocks."""
    if not sections or n_blocks == 0:
        return False
    return any(len(s.block_indices) < _MIN_BLOCKS_PER_SECTION for s in sections)


# ---------------------------------------------------------------------------
# prompt assembly
# ---------------------------------------------------------------------------


def _build_layout_block(
    sections: list[DigestSection],
    block_titles: list[str],
) -> str:
    lines: list[str] = []
    block_num = 1
    for sec in sections:
        tag = " [SMALL]" if len(sec.block_indices) < _MIN_BLOCKS_PER_SECTION else ""
        lines.append(f"SECTION{tag}: {sec.title}")
        for bi in sec.block_indices:
            lines.append(f"  {block_num}. {block_titles[bi]}")
            block_num += 1
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\*{0,2}SECTION:\*{0,2}\s*(.+)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"^\*{0,2}SECTION_SUMMARY:\*{0,2}\s*(.+)", re.IGNORECASE)
_BLOCKS_RE = re.compile(r"^\*{0,2}BLOCKS:\*{0,2}\s*(.+)", re.IGNORECASE)


def _parse_block_nums(text: str) -> list[int]:
    """Parse comma-separated 1-based block numbers into 0-based indices."""
    result: list[int] = []
    for part in text.split(","):
        stripped = part.strip()
        if stripped.isdigit():
            result.append(int(stripped) - 1)
    return result


def _validate_coverage(
    sections: list[DigestSection],
    n_blocks: int,
) -> list[DigestSection] | None:
    """Validate block coverage and salvage small omissions.

    Returns ``None`` when the output has duplicates, out-of-range indices,
    or more than 5% missing blocks.
    """
    seen: set[int] = set()
    for sec in sections:
        for idx in sec.block_indices:
            if idx < 0 or idx >= n_blocks or idx in seen:
                return None
            seen.add(idx)

    missing = set(range(n_blocks)) - seen
    max_missing = max(1, n_blocks // 20)  # tolerate up to 5%
    if len(missing) > max_missing:
        return None

    if missing:
        logger.warning(
            "[cyan]refine_layout:[/cyan] LLM omitted %d block(s) %s — appending to last section",
            len(missing),
            sorted(idx + 1 for idx in missing),
        )
        sections[-1].block_indices.extend(sorted(missing))

    return sections


def _parse_refine_output(
    text: str,
    n_blocks: int,
) -> list[DigestSection] | None:
    """Parse RefineLayout LLM output into sections.

    Returns ``None`` when the output is invalid (missing/duplicate blocks).
    The caller falls back to the original sections in that case.
    """
    sections: list[DigestSection] = []
    cur_title: str | None = None
    cur_summary = ""
    cur_blocks: list[int] = []

    def _flush() -> None:
        if cur_title is not None and cur_blocks:
            sections.append(
                DigestSection(title=cur_title, block_indices=list(cur_blocks), summary=cur_summary),
            )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _SECTION_RE.match(line)
        if m:
            _flush()
            cur_title = m.group(1).strip().strip("*")
            cur_summary = ""
            cur_blocks = []
            continue

        m = _SUMMARY_RE.match(line)
        if m:
            cur_summary = m.group(1).strip().strip("*")
            continue

        m = _BLOCKS_RE.match(line)
        if m:
            cur_blocks.extend(_parse_block_nums(m.group(1)))
            continue

    _flush()

    if not sections:
        return None

    return _validate_coverage(sections, n_blocks)


# ---------------------------------------------------------------------------
# remapping helpers
# ---------------------------------------------------------------------------


def _build_prompt_mapping(sections: list[DigestSection]) -> list[int]:
    """Build the global prompt-number → actual-block-index mapping.

    Blocks are numbered 1..N across all sections in order.  This list
    maps prompt position ``i`` (0-based) to the real ``block_indices``
    value from the original sections.
    """
    mapping: list[int] = []
    for sec in sections:
        for bi in sec.block_indices:
            mapping.append(bi)
    return mapping


def _remap_sections(
    refined: list[DigestSection],
    prompt_num_to_block_idx: list[int],
) -> list[DigestSection]:
    """Translate parser's prompt-based indices back to real block indices.

    Uses ``dict.fromkeys`` to collapse duplicates that appear when
    dedup/fuzzy-merge made two prompt positions point to the same real
    block and refine_layout later placed both into one section.
    """
    return [
        DigestSection(
            title=sec.title,
            block_indices=list(
                dict.fromkeys(prompt_num_to_block_idx[i] for i in sec.block_indices),
            ),
            summary=sec.summary,
        )
        for sec in refined
    ]


# ---------------------------------------------------------------------------
# task launcher
# ---------------------------------------------------------------------------


class RefineLayout(TaskLauncher):
    """Absorb small (1-2 block) sections into larger ones via a lightweight LLM pass.

    Reads ``ctx.digest.blocks`` and ``ctx.digest.recaps`` produced by
    OneshotDigest.  Only sections with fewer than ``_MIN_BLOCKS_PER_SECTION``
    blocks are candidates for absorption; larger sections are left untouched.

    Gated by ``needs_refinement`` — skips the LLM call when all sections
    already have >= ``_MIN_BLOCKS_PER_SECTION`` blocks.
    """

    name = "refine_layout"

    def execute(self) -> None:
        ctx = self.ctx
        blocks = ctx.digest.blocks
        sections = ctx.digest.recaps

        if not blocks or not sections:
            logger.info("[cyan]refine_layout:[/cyan] No blocks/sections — skipping")
            return

        if not needs_refinement(sections, len(blocks)):
            logger.info("[cyan]refine_layout:[/cyan] Layout clean — skipping refinement")
            return

        block_titles = [b.title for b in blocks]
        prompt_num_to_block_idx = _build_prompt_mapping(sections)

        layout_block = _build_layout_block(sections, block_titles)
        language = language_display_name(ctx.inp.preferences.language)

        prompt = render_prompt(
            RECAP_REFINE_LAYOUT_PROMPT,
            ctx.inp.prompt_backend,
            layout_block=layout_block,
            language=language,
            total_blocks=str(len(prompt_num_to_block_idx)),
        )

        stdout_path = run_single_agent(ctx, "recap_refine_layout", prompt)
        text = read_agent_stdout(stdout_path, "recap_refine_layout")

        refined = _parse_refine_output(text, len(prompt_num_to_block_idx))

        if refined is None:
            logger.warning(
                "[cyan]refine_layout:[/cyan] Invalid LLM output — keeping original sections",
            )
            return

        remapped = _remap_sections(refined, prompt_num_to_block_idx)
        ctx.digest.recaps = remapped
        logger.info(
            "[cyan]refine_layout:[/cyan] Refined %d → %d sections",
            len(sections),
            len(remapped),
        )

    def restore_state(self) -> None:
        pass
