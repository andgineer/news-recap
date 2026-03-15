"""Task launcher: ONESHOT_DIGEST phase.

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
from news_recap.recap.tasks.prompts import RECAP_ONESHOT_DIGEST_PROMPT, render_prompt

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

_MIN_COVERAGE = 0.50


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


class _Parser:
    """Stateful line-by-line parser for oneshot_digest LLM output."""

    def __init__(self) -> None:
        self.sections: list[_ParsedSection] = []
        self.excluded_nums: list[str] = []
        self._current_section: _ParsedSection | None = None
        self._current_block: _ParsedBlock | None = None
        # mode: "block_summary" | "section_summary" | "articles" | "excluded" | None
        self._mode: str | None = None

    # ------------------------------------------------------------------
    # keyword-line handlers
    # ------------------------------------------------------------------

    def _on_section(self, title: str) -> None:
        self._finalize_block()
        self._finalize_section()
        self._current_section = _ParsedSection(title=title)
        self._mode = None

    def _on_section_summary(self, text: str) -> None:
        if self._current_section is None:
            logger.warning("[oneshot_digest] SECTION_SUMMARY before SECTION — discarding")
        else:
            self._current_section.summary = text
            self._mode = "section_summary"

    def _on_block(self, title: str) -> None:
        self._finalize_block()
        if self._current_section is None:
            logger.warning("[oneshot_digest] BLOCK before SECTION — discarding")
        else:
            self._current_block = _ParsedBlock(title=title)
        self._mode = None

    def _on_summary(self, text: str) -> None:
        if self._current_block is None:
            logger.warning("[oneshot_digest] SUMMARY before BLOCK — discarding")
        else:
            self._current_block.summary = text
            self._mode = "block_summary"

    def _on_articles(self, text: str) -> None:
        if self._current_block is None:
            logger.warning("[oneshot_digest] ARTICLES before BLOCK — discarding")
        else:
            self._current_block.article_nums.extend(_parse_nums(text))
            self._mode = "articles"

    def _on_excluded(self, text: str) -> None:
        self.excluded_nums.extend(_parse_nums(text))
        self._mode = "excluded"

    # ------------------------------------------------------------------
    # continuation
    # ------------------------------------------------------------------

    def _on_continuation(self, line: str) -> None:
        mode, blk, sec = self._mode, self._current_block, self._current_section
        if mode == "block_summary" and blk is not None:
            blk.summary = (blk.summary + " " + line).strip()
        elif mode == "section_summary" and sec is not None:
            sec.summary = (sec.summary + " " + line).strip()
        elif mode == "articles" and blk is not None and _RE_NUMS_ONLY.match(line):
            blk.article_nums.extend(_parse_nums(line))
        elif mode == "excluded" and _RE_NUMS_ONLY.match(line):
            self.excluded_nums.extend(_parse_nums(line))
        else:
            self._mode = None

    # ------------------------------------------------------------------
    # finalization helpers
    # ------------------------------------------------------------------

    def _finalize_block(self) -> None:
        blk = self._current_block
        if blk is not None and self._current_section is not None and blk.article_nums:
            self._current_section.blocks.append(blk)
        self._current_block = None

    def _finalize_section(self) -> None:
        sec = self._current_section
        if sec is not None and sec.title and sec.blocks:
            self.sections.append(sec)
        self._current_section = None

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def feed(self, text: str) -> None:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            m = _RE_SECTION.match(line)
            if m:
                self._on_section(m.group(1).strip())
                continue
            m = _RE_SECTION_SUMMARY.match(line)
            if m:
                self._on_section_summary(m.group(1).strip())
                continue
            m = _RE_BLOCK.match(line)
            if m:
                self._on_block(m.group(1).strip())
                continue
            m = _RE_SUMMARY.match(line)
            if m:
                self._on_summary(m.group(1).strip())
                continue
            m = _RE_ARTICLES.match(line)
            if m:
                self._on_articles(m.group(1))
                continue
            m = _RE_EXCLUDED.match(line)
            if m:
                self._on_excluded(m.group(1))
                continue
            self._on_continuation(line)
        self._finalize_block()
        self._finalize_section()


def _parse_output(text: str) -> tuple[list[_ParsedSection], list[str]]:
    """Parse oneshot_digest LLM output into sections and excluded article numbers.

    Returns ``(sections, excluded_nums)`` where article numbers are raw strings.
    """
    parser = _Parser()
    parser.feed(text)
    return parser.sections, parser.excluded_nums


class OneshotDigest(TaskLauncher):
    """Single LLM call that groups articles into sections and summarises them."""

    name = "oneshot_digest"

    def execute(self) -> None:
        ctx = self.ctx
        kept_articles = ctx.digest.articles

        if not kept_articles:
            logger.info("[oneshot_digest] No articles to process — skipping")
            return

        logger.info("[oneshot_digest] Loading embedding model for pre-sort…")
        embedder = SentenceTransformerEmbedder(model_name=ctx.inp.dedup_model_name)
        ordered = reorder_articles(kept_articles, embedder, _GROUP_THRESHOLD)
        articles_block = build_article_lines(ordered)
        num_to_id = {str(i + 1): a.article_id for i, a in enumerate(ordered)}
        language = language_display_name(ctx.inp.preferences.language)

        backend = ctx.inp.prompt_backend
        prompt = render_prompt(
            RECAP_ONESHOT_DIGEST_PROMPT,
            backend,
            articles_block=articles_block,
            language=language,
        )
        stdout_path = run_single_agent(ctx, "recap_oneshot_digest", prompt)
        text = read_agent_stdout(stdout_path, "recap_oneshot_digest")

        parsed_sections, excluded_nums = _parse_output(text)

        excluded_ids = list({num_to_id[n] for n in excluded_nums if n in num_to_id})
        if excluded_ids:
            logger.info("[oneshot_digest] %d article(s) excluded by model", len(excluded_ids))

        blocks: list[DigestBlock] = []
        sections: list[DigestSection] = []

        for section in parsed_sections:
            block_start = len(blocks)
            for block in section.blocks:
                article_ids = [num_to_id[n] for n in block.article_nums if n in num_to_id]
                if not article_ids:
                    logger.warning(
                        "[oneshot_digest] block %r has no valid article IDs — skipping",
                        block.title,
                    )
                    continue
                blocks.append(
                    DigestBlock(
                        title=block.title,
                        article_ids=article_ids,
                        summary=block.summary,
                    ),
                )
            if len(blocks) == block_start:
                logger.warning(
                    "[oneshot_digest] section %r has no valid blocks — skipping",
                    section.title,
                )
                continue
            sections.append(
                DigestSection(
                    title=section.title,
                    block_indices=list(range(block_start, len(blocks))),
                    summary=section.summary,
                ),
            )

        # Coverage check
        assigned = {aid for b in blocks for aid in b.article_ids}
        effective = len(kept_articles) - len(excluded_ids)
        coverage = len(assigned) / effective if effective > 0 else 0.0

        if effective == 0 or coverage < _MIN_COVERAGE:
            raise RecapPipelineError(
                "recap_oneshot_digest",
                f"coverage too low: {coverage:.0%} ({len(assigned)}/{effective} articles assigned)",
            )

        ctx.digest.blocks = blocks
        ctx.digest.recaps = sections
        logger.info(
            "[oneshot_digest] %d section(s), %d block(s), coverage %.0f%%",
            len(sections),
            len(blocks),
            coverage * 100,
        )

    def restore_state(self) -> None:
        # blocks and recaps already restored from digest.json by _load_checkpoint()
        pass
