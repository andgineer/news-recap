"""Task launcher: SINGLE_PASS_DIGEST phase.

Replaces MapBlocks + ReduceBlocks + SplitBlocks + GroupSections + Summarize with a
single LLM call that groups, organises into sections, and summarises in one shot.

The article list is pre-sorted by embedding similarity so the model can focus on
editorial quality rather than topical grouping.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from news_recap.recap.article_ordering import build_article_lines, reorder_articles
from news_recap.recap.dedup.embedder import SentenceTransformerEmbedder
from news_recap.recap.models import DigestBlock, DigestSection, language_display_name
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
    run_single_agent,
)
from news_recap.recap.tasks.prompts import RECAP_SINGLE_PASS_PROMPT, render_prompt

logger = logging.getLogger(__name__)

_GROUP_THRESHOLD = 0.65  # embedding similarity threshold for pre-sort clustering

# Keyword prefix patterns (case-insensitive)
_RE_SECTION = re.compile(r"^section:\s*(.*)", re.IGNORECASE)
_RE_SECTION_SUMMARY = re.compile(r"^section_summary:\s*(.*)", re.IGNORECASE)
_RE_BLOCK = re.compile(r"^block:\s*(.*)", re.IGNORECASE)
_RE_SUMMARY = re.compile(r"^summary:\s*(.*)", re.IGNORECASE)
_RE_ARTICLES = re.compile(r"^articles:\s*(.*)", re.IGNORECASE)
_RE_EXCLUDED = re.compile(r"^excluded:\s*(.*)", re.IGNORECASE)
_RE_NUMS_ONLY = re.compile(r"^[\d,\s]+$")


@dataclass
class _ParsedBlock:
    title: str
    summary: str = ""
    article_nums: list[str] = field(default_factory=list)


@dataclass
class _ParsedSection:
    title: str
    summary: str = ""
    blocks: list[_ParsedBlock] = field(default_factory=list)


def _parse_nums(text: str) -> list[str]:
    return [n.strip() for n in text.split(",") if n.strip().isdigit()]


def _parse_output(text: str) -> tuple[list[_ParsedSection], list[str]]:
    """Parse single-pass LLM output into sections and excluded article numbers.

    Returns ``(sections, excluded_nums)`` where article numbers are raw strings.
    """
    sections: list[_ParsedSection] = []
    excluded_nums: list[str] = []

    current_section: _ParsedSection | None = None
    current_block: _ParsedBlock | None = None
    # mode: "block_summary" | "section_summary" | "articles" | "excluded" | None
    mode: str | None = None

    def _finalize_block() -> None:
        nonlocal current_block
        if current_block is not None and current_section is not None and current_block.article_nums:
            current_section.blocks.append(current_block)
        current_block = None

    def _finalize_section() -> None:
        nonlocal current_section
        if current_section is not None and current_section.title and current_section.blocks:
            sections.append(current_section)
        current_section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        m = _RE_SECTION.match(line)
        if m:
            _finalize_block()
            _finalize_section()
            current_section = _ParsedSection(title=m.group(1).strip())
            mode = None
            continue

        m = _RE_SECTION_SUMMARY.match(line)
        if m:
            if current_section is None:
                logger.warning("[single_pass] SECTION_SUMMARY before SECTION — discarding")
            else:
                current_section.summary = m.group(1).strip()
                mode = "section_summary"
            continue

        m = _RE_BLOCK.match(line)
        if m:
            _finalize_block()
            if current_section is None:
                logger.warning("[single_pass] BLOCK before SECTION — discarding")
            else:
                current_block = _ParsedBlock(title=m.group(1).strip())
            mode = None
            continue

        m = _RE_SUMMARY.match(line)
        if m:
            if current_block is None:
                logger.warning("[single_pass] SUMMARY before BLOCK — discarding")
            else:
                current_block.summary = m.group(1).strip()
                mode = "block_summary"
            continue

        m = _RE_ARTICLES.match(line)
        if m:
            if current_block is None:
                logger.warning("[single_pass] ARTICLES before BLOCK — discarding")
            else:
                current_block.article_nums.extend(_parse_nums(m.group(1)))
                mode = "articles"
            continue

        m = _RE_EXCLUDED.match(line)
        if m:
            excluded_nums.extend(_parse_nums(m.group(1)))
            mode = "excluded"
            continue

        # Continuation lines
        if not line:
            continue
        if mode == "block_summary" and current_block is not None:
            current_block.summary = (current_block.summary + " " + line).strip()
        elif mode == "section_summary" and current_section is not None:
            current_section.summary = (current_section.summary + " " + line).strip()
        elif mode == "articles" and current_block is not None and _RE_NUMS_ONLY.match(line):
            current_block.article_nums.extend(_parse_nums(line))
        elif mode == "excluded" and _RE_NUMS_ONLY.match(line):
            excluded_nums.extend(_parse_nums(line))
        else:
            mode = None  # non-matching continuation exits current mode

    _finalize_block()
    _finalize_section()
    return sections, excluded_nums


class SinglePassDigest(TaskLauncher):
    """Single LLM call that groups articles into sections and summarises them."""

    name = "single_pass_digest"

    def execute(self) -> None:
        ctx = self.ctx
        kept_articles = ctx.digest.articles

        if not kept_articles:
            logger.info("[single_pass] No articles to process — skipping")
            return

        logger.info("[single_pass] Loading embedding model for pre-sort…")
        embedder = SentenceTransformerEmbedder(model_name=ctx.inp.dedup_model_name)
        ordered = reorder_articles(kept_articles, embedder, _GROUP_THRESHOLD)
        articles_block = build_article_lines(ordered)
        num_to_id = {str(i + 1): a.article_id for i, a in enumerate(ordered)}
        language = language_display_name(ctx.inp.preferences.language)

        backend = ctx.inp.prompt_backend
        prompt = render_prompt(
            RECAP_SINGLE_PASS_PROMPT,
            backend,
            articles_block=articles_block,
            language=language,
        )
        stdout_path = run_single_agent(ctx, "recap_single_pass", prompt)
        text = read_agent_stdout(stdout_path, "recap_single_pass")

        parsed_sections, excluded_nums = _parse_output(text)

        excluded_ids = list({num_to_id[n] for n in excluded_nums if n in num_to_id})
        if excluded_ids:
            logger.info("[single_pass] %d article(s) excluded by model", len(excluded_ids))

        blocks: list[DigestBlock] = []
        sections: list[DigestSection] = []

        for section in parsed_sections:
            block_start = len(blocks)
            for block in section.blocks:
                article_ids = [num_to_id[n] for n in block.article_nums if n in num_to_id]
                if not article_ids:
                    logger.warning(
                        "[single_pass] block %r has no valid article IDs — skipping",
                        block.title,
                    )
                    continue
                blocks.append(
                    DigestBlock(
                        title=block.title,
                        article_ids=article_ids,
                        summary=block.summary,
                    )
                )
            if len(blocks) == block_start:
                logger.warning(
                    "[single_pass] section %r has no valid blocks — skipping",
                    section.title,
                )
                continue
            sections.append(
                DigestSection(
                    title=section.title,
                    block_indices=list(range(block_start, len(blocks))),
                    summary=section.summary,
                )
            )

        # Coverage check
        assigned = {aid for b in blocks for aid in b.article_ids}
        effective = len(kept_articles) - len(excluded_ids)
        coverage = len(assigned) / effective if effective > 0 else 0.0

        if effective == 0 or coverage < 0.50:
            raise RecapPipelineError(
                "recap_single_pass",
                f"coverage too low: {coverage:.0%} ({len(assigned)}/{effective} articles assigned)",
            )

        ctx.digest.blocks = blocks
        ctx.digest.recaps = sections
        logger.info(
            "[single_pass] %d section(s), %d block(s), coverage %.0f%%",
            len(sections),
            len(blocks),
            coverage * 100,
        )

    def restore_state(self) -> None:
        # blocks and recaps already restored from digest.json by _load_checkpoint()
        pass
