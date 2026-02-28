"""Task launcher: SUMMARIZE phase — produce a day summary.

Reads the section structure (``digest.recaps``) and block titles,
then asks an LLM to write a heading + bulleted storylines summary.
"""

from __future__ import annotations

import logging
from pathlib import Path

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.storage.pipeline_io import materialize_step
from news_recap.recap.tasks.base import RecapPipelineError, TaskLauncher
from news_recap.recap.tasks.prompts import RECAP_SUMMARIZE_PROMPT

logger = logging.getLogger(__name__)

_START_MARKER = "SUMMARY_START"
_END_MARKER = "SUMMARY_END"


def build_summarize_prompt(
    sections: list[DigestSection],
    blocks: list[DigestBlock],
    language: str,
) -> str:
    """Build the SUMMARIZE prompt from sections and their blocks."""
    parts: list[str] = []
    for section in sections:
        parts.append(f"## {section.title}")
        for idx in section.block_indices:
            if 0 <= idx < len(blocks):
                parts.append(f"  - {blocks[idx].title}")
        parts.append("")
    return RECAP_SUMMARIZE_PROMPT.format(
        language=language,
        digest_overview="\n".join(parts),
    )


def parse_summarize_stdout(stdout_path: Path) -> str:
    """Extract summary text between SUMMARY_START / SUMMARY_END markers."""
    if not stdout_path.exists():
        raise RecapPipelineError(
            "recap_summarize",
            f"SUMMARIZE stdout not found: {stdout_path}",
        )

    text = stdout_path.read_text("utf-8")
    if not text.strip():
        raise RecapPipelineError("recap_summarize", "SUMMARIZE stdout is empty")

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
        pf_logger = get_run_logger()

        if not ctx.digest.recaps:
            pf_logger.info("[summarize] No sections — skipping summary")
            ctx.digest.day_summary = ""
            return

        prompt = build_summarize_prompt(
            ctx.digest.recaps,
            ctx.digest.blocks,
            ctx.inp.preferences.language,
        )
        tid = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_summarize",
            prompt=prompt,
        )

        tid = run_ai_agent.with_options(task_run_name=tid)(
            pipeline_dir=str(ctx.pdir),
            step_name="recap_summarize",
            task_id=tid,
        )

        stdout_path = ctx.pdir / tid / "output" / "agent_stdout.log"
        ctx.digest.day_summary = parse_summarize_stdout(stdout_path)

        pf_logger.info(
            "[summarize] Day summary: %d chars",
            len(ctx.digest.day_summary),
        )
