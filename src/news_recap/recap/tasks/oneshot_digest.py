"""Task launcher: ONESHOT_DIGEST phase.

A single LLM call (or batched parallel calls for large article sets) that groups
articles into blocks, organises blocks into sections, and summarises in one shot.

The article list is pre-sorted by embedding similarity so the model can focus on
editorial quality rather than topical grouping.  When the article count exceeds
_BATCH_SIZE the list is split into chunks that are processed in parallel; a final
merge call reconciles duplicate section names across batches.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from news_recap.recap.article_ordering import build_article_lines, reorder_articles
from news_recap.recap.dedup.cluster import group_similar
from news_recap.recap.dedup.embedder import Embedder, SentenceTransformerEmbedder, Vector
from news_recap.recap.models import DigestArticle, DigestBlock, DigestSection, language_display_name
from news_recap.recap.storage.workdir import make_task_id
from news_recap.recap.tasks.base import (
    FlowContext,
    RecapPipelineError,
    TaskLauncher,
    log_parse_failure,
    read_agent_stdout,
    run_single_agent,
)
from news_recap.recap.tasks.prompts import (
    RECAP_MERGE_SECTIONS_PROMPT,
    RECAP_ONESHOT_DIGEST_PROMPT,
    render_prompt,
)

logger = logging.getLogger(__name__)

_GROUP_THRESHOLD = 0.65  # embedding similarity threshold for pre-sort clustering
_BATCH_SIZE = 200  # max articles per oneshot LLM call
_ORDER_FILENAME = "oneshot_digest_order.json"

# ---------------------------------------------------------------------------
# oneshot_digest output parser regexes
# ---------------------------------------------------------------------------

_RE_SECTION = re.compile(r"^section:\s*(.*)", re.IGNORECASE)
_RE_SECTION_SUMMARY = re.compile(r"^section_summary:\s*(.*)", re.IGNORECASE)
_RE_SUMMARY = re.compile(r"^summary:\s*(.*)", re.IGNORECASE)
_RE_BLOCK = re.compile(r"^block:\s*(.*)", re.IGNORECASE)
_RE_ARTICLES = re.compile(r"^articles:\s*(.*)", re.IGNORECASE)
_RE_EXCLUDED = re.compile(r"^excluded:\s*(.*)", re.IGNORECASE)
_RE_NUMS_ONLY = re.compile(r"^[\d,\s]+$")

# merge output parser regexes
_RE_INCLUDES = re.compile(r"^includes:\s*(.*)", re.IGNORECASE)

_MIN_COVERAGE = 0.50


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


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


@dataclass
class _MergedSection:
    title: str
    summary: str
    source_indices: list[int]  # 1-based indices into the flat all_sections list


# ---------------------------------------------------------------------------
# oneshot_digest output parser
# ---------------------------------------------------------------------------


def _parse_nums(text: str) -> list[str]:
    return [n.strip() for n in text.split(",") if n.strip().isdigit()]


class _Parser:
    """Stateful line-by-line parser for oneshot_digest LLM output."""

    def __init__(self) -> None:
        self.sections: list[_ParsedSection] = []
        self.excluded_nums: list[str] = []
        self._current_section: _ParsedSection | None = None
        self._current_block: _ParsedBlock | None = None
        # mode: "block_title" | "block_summary" | "section_summary" | "articles" | "excluded" | None
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
            logger.warning(
                "[cyan]oneshot_digest:[/cyan] SECTION_SUMMARY before SECTION — discarding",
            )
        else:
            self._current_section.summary = text
            self._mode = "section_summary"

    def _on_summary(self, text: str) -> None:
        """SUMMARY: sets the current block's summary.

        Falls back to section summary if no block is active.
        """
        if self._current_block is not None:
            self._current_block.summary = text
            self._mode = "block_summary"
        else:
            self._on_section_summary(text)

    def _on_block(self, title: str) -> None:
        self._finalize_block()
        if self._current_section is None:
            logger.warning("[cyan]oneshot_digest:[/cyan] BLOCK before SECTION — discarding")
        else:
            self._current_block = _ParsedBlock(title=title)
            self._mode = "block_title"

    def _on_articles(self, text: str) -> None:
        if self._current_block is None:
            logger.warning("[cyan]oneshot_digest:[/cyan] ARTICLES before BLOCK — discarding")
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
        if mode == "block_title" and blk is not None:
            blk.title = (blk.title + " " + line).strip()
        elif mode == "block_summary" and blk is not None:
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


# ---------------------------------------------------------------------------
# merge output parser
# ---------------------------------------------------------------------------


def _parse_merge_output(text: str) -> list[_MergedSection]:
    """Parse merge_sections LLM output.

    Each entry is::

        SECTION: <title>
        SECTION_SUMMARY: <combined summary>
        INCLUDES: 1, 3, 7
    """
    results: list[_MergedSection] = []
    current_title: str | None = None
    current_summary: str = ""
    current_indices: list[int] = []

    def _flush() -> None:
        if current_title is not None and current_indices:
            results.append(
                _MergedSection(
                    title=current_title,
                    summary=current_summary,
                    source_indices=current_indices,
                ),
            )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _RE_SECTION.match(line)
        if m:
            _flush()
            current_title = m.group(1).strip()
            current_summary = ""
            current_indices = []
            continue
        m = _RE_SECTION_SUMMARY.match(line) or _RE_SUMMARY.match(line)
        if m:
            current_summary = m.group(1).strip()
            continue
        m = _RE_INCLUDES.match(line)
        if m:
            current_indices = [int(n) for n in m.group(1).split(",") if n.strip().isdigit()]
            continue

    _flush()
    return results


# ---------------------------------------------------------------------------
# batch helpers
# ---------------------------------------------------------------------------


_BATCH_MAPPING_FILENAME = "batch_num_to_id.json"


def _read_cached_batch(
    ctx: FlowContext,
    batch_num: int | None,
) -> tuple[list[_ParsedSection], list[str], dict[str, str]] | None:
    """Return ``(sections, excluded_nums, num_to_id)`` from a previous run, or ``None``.

    Both the agent stdout and the stored ``num_to_id`` mapping are required;
    the mapping ensures article numbers are interpreted correctly even when
    ``reorder_articles`` produces a different ordering on resume.
    """
    task_id = make_task_id("recap_oneshot_digest", batch_num)
    stdout_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
    mapping_path = ctx.pdir / task_id / "input" / _BATCH_MAPPING_FILENAME
    if not stdout_path.exists() or not mapping_path.exists():
        return None
    try:
        text = stdout_path.read_text("utf-8")
        stored_num_to_id: dict[str, str] = json.loads(mapping_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not text.strip():
        return None
    sections, excluded_nums = _parse_output(text)
    if not sections:
        return None
    return sections, excluded_nums, stored_num_to_id


def _save_batch_mapping(ctx: FlowContext, batch_num: int | None, num_to_id: dict[str, str]) -> None:
    """Persist the article-number → article-ID mapping for cache reuse."""
    task_id = make_task_id("recap_oneshot_digest", batch_num)
    mapping_path = ctx.pdir / task_id / "input" / _BATCH_MAPPING_FILENAME
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(num_to_id), "utf-8")


def _run_batch(
    ctx: FlowContext,
    batch_num: int | None,
    articles_batch: list[DigestArticle],
    language: str,
    *,
    use_cache: bool = True,
) -> tuple[list[_ParsedSection], list[str], dict[str, str]]:
    """Run one oneshot_digest LLM call for a slice of articles.

    Returns ``(parsed_sections, excluded_ids, num_to_id)``.

    When *use_cache* is ``True`` and a previous (interrupted) run left
    valid output with a stored ``num_to_id`` mapping, that output is
    reused.  Set *use_cache* to ``False`` when the article ordering was
    recomputed (cached results correspond to a different batch composition).
    """
    cached = _read_cached_batch(ctx, batch_num) if use_cache else None
    if cached is not None:
        parsed_sections, excluded_nums, stored_num_to_id = cached
        excluded_ids = [stored_num_to_id[n] for n in excluded_nums if n in stored_num_to_id]
        logger.info(
            "[cyan]oneshot_digest:[/cyan] batch %s → reusing cached result"
            " (%d section(s), %d excluded)",
            batch_num or 1,
            len(parsed_sections),
            len(excluded_ids),
        )
        return parsed_sections, excluded_ids, stored_num_to_id

    num_to_id = {str(i + 1): a.article_id for i, a in enumerate(articles_batch)}
    articles_block = build_article_lines(articles_batch)
    prompt = render_prompt(
        RECAP_ONESHOT_DIGEST_PROMPT,
        ctx.inp.prompt_backend,
        articles_block=articles_block,
        language=language,
        follow_policy=ctx.inp.preferences.follow or "none",
    )
    label = f"recap_oneshot_digest (batch {batch_num})" if batch_num else "recap_oneshot_digest"
    stdout_path = run_single_agent(ctx, "recap_oneshot_digest", prompt, batch=batch_num)
    _save_batch_mapping(ctx, batch_num, num_to_id)
    text = read_agent_stdout(stdout_path, label)
    parsed_sections, excluded_nums = _parse_output(text)
    if not parsed_sections:
        log_parse_failure("Oneshot digest", text, log=logger)
    excluded_ids = [num_to_id[n] for n in excluded_nums if n in num_to_id]
    logger.info(
        "[cyan]oneshot_digest:[/cyan] batch %s → %d section(s), %d excluded",
        batch_num or 1,
        len(parsed_sections),
        len(excluded_ids),
    )
    return parsed_sections, excluded_ids, num_to_id


def _run_merge(
    ctx: FlowContext,
    all_sections: list[tuple[_ParsedSection, dict[str, str]]],
    language: str,
) -> list[_MergedSection]:
    """Run the merge LLM call that consolidates sections from multiple batches."""
    sections_block = "\n".join(
        f'{i + 1}. "{sec.title}" — {sec.summary}' for i, (sec, _) in enumerate(all_sections)
    )
    prompt = render_prompt(
        RECAP_MERGE_SECTIONS_PROMPT,
        ctx.inp.prompt_backend,
        sections_block=sections_block,
        total=str(len(all_sections)),
        language=language,
        follow_policy=ctx.inp.preferences.follow or "none",
    )
    stdout_path = run_single_agent(ctx, "recap_merge_sections", prompt)
    text = read_agent_stdout(stdout_path, "recap_merge_sections")
    merged = _parse_merge_output(text)
    logger.info(
        "[cyan]oneshot_digest:[/cyan] merge → %d final section(s) from %d source(s)",
        len(merged),
        len(all_sections),
    )
    return merged


def _build_digest_entries(
    parsed_sections: list[_ParsedSection],
    num_to_id: dict[str, str],
) -> tuple[list[DigestBlock], list[DigestSection]]:
    """Convert parsed sections + num_to_id into DigestBlock/DigestSection objects."""
    blocks: list[DigestBlock] = []
    sections: list[DigestSection] = []
    for section in parsed_sections:
        block_start = len(blocks)
        for block in section.blocks:
            article_ids = [num_to_id[n] for n in block.article_nums if n in num_to_id]
            if not article_ids:
                logger.warning(
                    "[cyan]oneshot_digest:[/cyan] block %r has no valid article IDs — skipping",
                    block.title,
                )
                continue
            blocks.append(DigestBlock(title=block.title, article_ids=article_ids))
        if len(blocks) == block_start:
            logger.warning(
                "[cyan]oneshot_digest:[/cyan] section %r has no valid blocks — skipping",
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
    return blocks, sections


def _build_merged_digest_entries(
    merged: list[_MergedSection],
    all_sections: list[tuple[_ParsedSection, dict[str, str]]],  # noqa: E501
) -> tuple[list[DigestBlock], list[DigestSection]]:
    """Build DigestBlock/DigestSection from merge output, combining blocks across batches."""
    blocks: list[DigestBlock] = []
    sections: list[DigestSection] = []
    for ms in merged:
        block_start = len(blocks)
        for idx in ms.source_indices:
            if idx < 1 or idx > len(all_sections):
                logger.warning(
                    "[cyan]oneshot_digest:[/cyan] merge INCLUDES out-of-range index %d — skipping",
                    idx,
                )
                continue
            src_sec, num_to_id = all_sections[idx - 1]
            for block in src_sec.blocks:
                article_ids = [num_to_id[n] for n in block.article_nums if n in num_to_id]
                if not article_ids:
                    continue
                blocks.append(
                    DigestBlock(title=block.title, summary=block.summary, article_ids=article_ids),
                )
        if len(blocks) == block_start:
            logger.warning(
                "[cyan]oneshot_digest:[/cyan] merged section %r has no valid blocks — skipping",
                ms.title,
            )
            continue
        sections.append(
            DigestSection(
                title=ms.title,
                block_indices=list(range(block_start, len(blocks))),
                summary=ms.summary,
            ),
        )
    return blocks, sections


# ---------------------------------------------------------------------------
# block dedup
# ---------------------------------------------------------------------------


def _collapse_exact_dupes(
    blocks: list[DigestBlock],
    keys: list[frozenset[str]],
) -> tuple[dict[int, int], int]:
    """Return ``survivors`` map (old_idx → winner old_idx) and count of removed."""
    exact_groups: dict[frozenset[str], list[int]] = {}
    for idx, key in enumerate(keys):
        exact_groups.setdefault(key, []).append(idx)

    survivors: dict[int, int] = {}
    for indices in exact_groups.values():
        winner = max(indices, key=lambda i: (len(blocks[i].title), -i))
        for i in indices:
            survivors[i] = winner

    return survivors, len(blocks) - len(exact_groups)


def _find_subset_absorptions(
    unique_indices: list[int],
    keys: list[frozenset[str]],
) -> dict[int, int]:
    """Return ``absorbed`` map (subset_idx → superset_idx), smallest superset wins."""
    unique_keys = {i: keys[i] for i in unique_indices}
    absorbed: dict[int, int] = {}
    for i in unique_indices:
        for j in unique_indices:
            if i == j:
                continue
            if unique_keys[i] < unique_keys[j]:  # strict subset
                prev = absorbed.get(i)
                if prev is None or len(unique_keys[j]) < len(unique_keys[prev]):
                    absorbed[i] = j
    return absorbed


def _resolve_chain(idx: int, absorbed: dict[int, int]) -> int:
    while idx in absorbed:
        idx = absorbed[idx]
    return idx


def _dedup_blocks(
    blocks: list[DigestBlock],
    sections: list[DigestSection],
) -> tuple[list[DigestBlock], list[DigestSection]]:
    """Remove duplicate and subset blocks, rewrite section block_indices.

    Phase 1 — exact duplicates: blocks whose ``article_ids`` sets are
    identical.  Longest title wins; ties broken by earlier position.

    Phase 2 — subset absorption: if block A's article set is a strict
    subset of block B's, A is absorbed into B (redundant).
    """
    n = len(blocks)
    keys = [frozenset(block.article_ids) for block in blocks]

    survivors, exact_removed = _collapse_exact_dupes(blocks, keys)

    unique_indices = sorted({survivors[i] for i in range(n)})
    absorbed = _find_subset_absorptions(unique_indices, keys)

    final_winners = sorted({_resolve_chain(v, absorbed) for v in survivors.values()})
    winner_to_new = {w: new_i for new_i, w in enumerate(final_winners)}

    old_to_new: dict[int, int] = {}
    for old_idx in range(n):
        old_to_new[old_idx] = winner_to_new[_resolve_chain(survivors[old_idx], absorbed)]

    deduped = [blocks[i] for i in final_winners]

    subset_removed = len(absorbed)
    if exact_removed or subset_removed:
        logger.info(
            "[cyan]oneshot_digest:[/cyan] dedup removed %d exact + %d subset block(s)",
            exact_removed,
            subset_removed,
        )

    new_sections: list[DigestSection] = []
    for sec in sections:
        remapped: list[int] = list(dict.fromkeys(old_to_new[i] for i in sec.block_indices))
        if not remapped:
            continue
        new_sections.append(
            DigestSection(title=sec.title, block_indices=remapped, summary=sec.summary),
        )

    return deduped, new_sections


# ---------------------------------------------------------------------------
# fuzzy block merge (Phase 3)
# ---------------------------------------------------------------------------

_FUZZY_MERGE_THRESHOLD = 0.90


def _apply_fuzzy_clusters(
    blocks: list[DigestBlock],
    clusters: list[list[str]],
) -> tuple[dict[int, DigestBlock], dict[int, int]]:
    """Process similarity clusters into merged blocks and an absorption map.

    Returns ``(merged_blocks, absorbed_to_winner)`` where *merged_blocks*
    maps each winner index to its merged ``DigestBlock`` and
    *absorbed_to_winner* maps each non-winner index to its winner.
    """
    merged_blocks: dict[int, DigestBlock] = {}
    absorbed_to_winner: dict[int, int] = {}

    for cluster in clusters:
        indices = sorted(int(c) for c in cluster)
        winner = max(
            indices,
            key=lambda i: (len(blocks[i].article_ids), len(blocks[i].title), -i),
        )
        combined_ids: list[str] = []
        for idx in indices:
            for aid in blocks[idx].article_ids:
                if aid not in combined_ids:
                    combined_ids.append(aid)
            if idx != winner:
                absorbed_to_winner[idx] = winner
        merged_blocks[winner] = DigestBlock(
            title=blocks[winner].title,
            summary=blocks[winner].summary,
            article_ids=combined_ids,
        )

    return merged_blocks, absorbed_to_winner


def _fuzzy_merge_blocks(
    blocks: list[DigestBlock],
    sections: list[DigestSection],
    embedder: Embedder,
    threshold: float = _FUZZY_MERGE_THRESHOLD,
) -> tuple[list[DigestBlock], list[DigestSection]]:
    """Merge blocks with highly similar titles via embedding cosine similarity.

    Phase 3 of dedup — catches cross-batch overlaps where two batches
    independently created blocks about the same story with different
    article sets.  Phases 1-2 (exact / subset) only compare article-id
    sets and cannot detect these.
    """
    if len(blocks) <= 1:
        return blocks, sections

    titles = [b.title for b in blocks]
    vectors = embedder.embed(titles)

    ids = [str(i) for i in range(len(blocks))]
    embeddings: dict[str, Vector] = dict(zip(ids, vectors, strict=True))

    clusters = group_similar(ids, embeddings, threshold, max_group_size=len(blocks))

    if not clusters:
        logger.debug("[cyan]oneshot_digest:[/cyan] fuzzy merge: no similar blocks found")
        return blocks, sections

    merged_blocks, absorbed_to_winner = _apply_fuzzy_clusters(blocks, clusters)
    consumed = set(merged_blocks.keys()) | set(absorbed_to_winner.keys())

    final_indices = sorted(
        set(merged_blocks.keys()) | (set(range(len(blocks))) - consumed),
    )
    old_to_new = {old: new for new, old in enumerate(final_indices)}
    for absorbed, winner in absorbed_to_winner.items():
        old_to_new[absorbed] = old_to_new[winner]

    new_blocks = [merged_blocks.get(i, blocks[i]) for i in final_indices]

    new_sections: list[DigestSection] = []
    for sec in sections:
        remapped: list[int] = list(
            dict.fromkeys(old_to_new[i] for i in sec.block_indices),
        )
        if remapped:
            new_sections.append(
                DigestSection(title=sec.title, block_indices=remapped, summary=sec.summary),
            )

    fuzzy_removed = len(blocks) - len(new_blocks)
    if fuzzy_removed:
        logger.info(
            "[cyan]oneshot_digest:[/cyan] fuzzy merge removed %d block(s)",
            fuzzy_removed,
        )

    return new_blocks, new_sections


# ---------------------------------------------------------------------------
# ordering persistence
# ---------------------------------------------------------------------------


def _load_or_restore_ordering(
    ctx: FlowContext,
    kept_articles: list[DigestArticle],
) -> tuple[list[DigestArticle], Embedder | None]:
    """Return the ordered article list and an optional embedder.

    On first run the embedding model is loaded, articles are reordered by
    similarity, and the resulting ID sequence is persisted to
    ``_ORDER_FILENAME``.  On resume the stored ordering is restored
    without loading the model (it is deferred until ``_fuzzy_merge_blocks``
    actually needs it).
    """
    order_path = ctx.pdir / _ORDER_FILENAME
    if order_path.exists():
        try:
            stored_ids: list[str] = json.loads(order_path.read_text("utf-8"))
            id_to_article = {a.article_id: a for a in kept_articles}
            restored = [id_to_article[aid] for aid in stored_ids if aid in id_to_article]
            if len(restored) == len(kept_articles):
                logger.info(
                    "[cyan]oneshot_digest:[/cyan] Restored article ordering from previous run",
                )
                return restored, None
        except (OSError, json.JSONDecodeError):
            pass
        logger.info(
            "[cyan]oneshot_digest:[/cyan] Stored ordering stale, recomputing…",
        )

    logger.info("[cyan]oneshot_digest:[/cyan] Loading embedding model for pre-sort…")
    embedder = SentenceTransformerEmbedder(model_name=ctx.inp.dedup_model_name)
    ordered = reorder_articles(kept_articles, embedder, _GROUP_THRESHOLD)
    order_path.write_text(
        json.dumps([a.article_id for a in ordered]),
        "utf-8",
    )
    return ordered, embedder


# ---------------------------------------------------------------------------
# Task launcher
# ---------------------------------------------------------------------------


class OneshotDigest(TaskLauncher):
    """One or more parallel LLM calls that group articles into sections and summarise them.

    For large article sets (> _BATCH_SIZE) the sorted article list is split into batches
    processed in parallel; a final merge call consolidates duplicate section names.
    """

    name = "oneshot_digest"

    def execute(self) -> None:
        ctx = self.ctx
        kept_articles = ctx.digest.articles

        if not kept_articles:
            logger.info("[cyan]oneshot_digest:[/cyan] No articles to process — skipping")
            return

        ordered, embedder = _load_or_restore_ordering(ctx, kept_articles)
        language = language_display_name(ctx.inp.preferences.language)
        # Cache is only safe when the ordering was restored (embedder is None);
        # a recomputed ordering means different batch composition.
        use_cache = embedder is None

        # Split into batches
        if len(ordered) <= _BATCH_SIZE:
            batches: list[list[DigestArticle]] = [ordered]
        else:
            batches = [ordered[i : i + _BATCH_SIZE] for i in range(0, len(ordered), _BATCH_SIZE)]

        logger.info(
            "[cyan]oneshot_digest:[/cyan] %d article(s) → %d batch(es)",
            len(ordered),
            len(batches),
        )

        # Run batches (parallel when more than one)
        batch_results: dict[int, tuple[list[_ParsedSection], list[str], dict[str, str]]] = {}

        if len(batches) == 1:
            sections, excluded_ids, num_to_id = _run_batch(
                ctx,
                None,
                batches[0],
                language,
                use_cache=use_cache,
            )
            batch_results[0] = (sections, excluded_ids, num_to_id)
        else:
            with ThreadPoolExecutor(max_workers=len(batches)) as executor:
                futures = {
                    executor.submit(
                        _run_batch,
                        ctx,
                        i + 1,
                        batch,
                        language,
                        use_cache=use_cache,
                    ): i
                    for i, batch in enumerate(batches)
                }
                for future in as_completed(futures):
                    i = futures[future]
                    batch_results[i] = future.result()

        all_excluded_ids: list[str] = []
        # flat list of (parsed_section, num_to_id) preserving batch order
        all_sections: list[tuple[_ParsedSection, dict[str, str]]] = []
        for i in range(len(batches)):
            parsed_sections, excluded_ids, num_to_id = batch_results[i]
            all_excluded_ids.extend(excluded_ids)
            for sec in parsed_sections:
                all_sections.append((sec, num_to_id))

        # Build final digest entries
        if len(batches) == 1:
            blocks, sections_out = _build_digest_entries(
                [s for s, _ in all_sections],
                all_sections[0][1] if all_sections else {},
            )
        else:
            merged = _run_merge(ctx, all_sections, language)
            blocks, sections_out = _build_merged_digest_entries(merged, all_sections)

        blocks, sections_out = _dedup_blocks(blocks, sections_out)
        if embedder is None:
            embedder = SentenceTransformerEmbedder(model_name=ctx.inp.dedup_model_name)
        blocks, sections_out = _fuzzy_merge_blocks(blocks, sections_out, embedder)

        # Coverage check
        unique_excluded = list(set(all_excluded_ids))
        assigned = {aid for b in blocks for aid in b.article_ids}
        effective = len(kept_articles) - len(unique_excluded)
        coverage = len(assigned) / effective if effective > 0 else 0.0

        if effective == 0 or coverage < _MIN_COVERAGE:
            raise RecapPipelineError(
                "recap_oneshot_digest",
                f"coverage too low: {coverage:.0%} ({len(assigned)}/{effective} articles assigned)",
            )

        ctx.digest.blocks = blocks
        ctx.digest.recaps = sections_out
        logger.info(
            "[cyan]oneshot_digest:[/cyan] %d section(s), %d block(s), coverage %.0f%%",
            len(sections_out),
            len(blocks),
            coverage * 100,
        )

    def restore_state(self) -> None:
        # blocks and recaps already restored from digest.json by _load_checkpoint()
        pass
