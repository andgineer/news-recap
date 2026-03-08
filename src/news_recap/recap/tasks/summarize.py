"""Task launcher: SUMMARIZE phase — produce a day summary.

Reads the section structure (``digest.recaps``) and block titles,
then asks an LLM to write a heading + bulleted storylines summary.
"""

from __future__ import annotations

import logging
from pathlib import Path

from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
    run_single_agent,
)
from news_recap.recap.tasks.prompts import RECAP_SUMMARIZE_PROMPT, PromptBackend, render_prompt

logger = logging.getLogger(__name__)

_START_MARKER = "SUMMARY_START"
_END_MARKER = "SUMMARY_END"


def build_summarize_prompt(
    sections: list[DigestSection],
    blocks: list[DigestBlock],
    language: str,
    backend: PromptBackend = PromptBackend.CLI,
) -> str:
    """Build the SUMMARIZE prompt from sections and their blocks."""
    parts: list[str] = []
    for section in sections:
        parts.append(f"## {section.title}")
        for idx in section.block_indices:
            if 0 <= idx < len(blocks):
                parts.append(f"  - {blocks[idx].title}")
        parts.append("")
    return render_prompt(
        RECAP_SUMMARIZE_PROMPT,
        backend,
        language=language,
        digest_overview="\n".join(parts),
    )


def parse_summarize_stdout(stdout_path: Path) -> str:
    """Extract summary text between SUMMARY_START / SUMMARY_END markers."""
    text = read_agent_stdout(stdout_path, "recap_summarize")

    start_pos = text.find(_START_MARKER)
    end_pos = text.find(_END_MARKER)

    if start_pos == -1 or end_pos == -1 or end_pos <= start_pos:
        raise RecapPipelineError(
            "recap_summarize",
            "SUMMARIZE stdout missing SUMMARY_START / SUMMARY_END markers",
        )

    content = text[start_pos + len(_START_MARKER) : end_pos].strip()
    if not content:
        raise RecapPipelineError("recap_summarize", "SUMMARIZE content between markers is empty")

    return content


class Summarize(TaskLauncher):
    """Produce a day summary from sections and block titles."""

    name = "summarize"

    def execute(self) -> None:
        ctx = self.ctx
        if not ctx.digest.recaps:
            logger.info("[summarize] No sections — skipping summary")
            ctx.digest.day_summary = ""
            return

        prompt = build_summarize_prompt(
            ctx.digest.recaps,
            ctx.digest.blocks,
            ctx.inp.preferences.language,
            ctx.inp.prompt_backend,
        )
        stdout_path = run_single_agent(ctx, "recap_summarize", prompt)
        ctx.digest.day_summary = parse_summarize_stdout(stdout_path)

        logger.info(
            "[summarize] Day summary: %d chars",
            len(ctx.digest.day_summary),
        )
