"""Task launcher: enrich articles flagged by classify as needing more context.

Uses inline prompt with article text and stdout-based output for new headlines.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from news_recap.recap.storage.pipeline_io import (
    load_cached_resource_texts,
    materialize_step,
    next_batch_number,
    resource_cache_dir,
)
from news_recap.recap.tasks.base import (
    FlowContext,
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
)
from news_recap.recap.tasks.parallel import submit_and_collect
from news_recap.recap.tasks.prompts import (
    RECAP_ENRICH_BATCH_PROMPT,
    PromptBackend,
    render_prompt,
)

logger = logging.getLogger(__name__)

_MAX_BATCH = 20
_MAX_ARTICLE_CHARS = 5_000
_MAX_BATCH_CHARS = 60_000
_MAX_ROUNDS = 3
_MAX_PARALLEL = 3
_MIN_RECOGNITION_RATE = 0.50
_ARTICLE_SEPARATOR = "===ARTICLE==="
_MIN_CHUNK_LINES = 2


# ---------------------------------------------------------------------------
# Batching / prompt / stdout parsing (enrich-specific)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EnrichEntry:
    """Article with loaded resource text ready for the enrich prompt."""

    article_id: str
    title: str
    text: str


def split_into_enrich_batches(entries: list[EnrichEntry]) -> list[list[EnrichEntry]]:
    """Split entries into batches respecting char budget and article count.

    Each batch stays within ``_MAX_BATCH_CHARS`` total article text
    and ``_MAX_BATCH`` articles.
    """
    if not entries:
        return []

    batches: list[list[EnrichEntry]] = []
    current: list[EnrichEntry] = []
    current_chars = 0

    for entry in entries:
        entry_chars = min(len(entry.text), _MAX_ARTICLE_CHARS) + len(entry.title) + 10
        if current and (
            len(current) >= _MAX_BATCH or current_chars + entry_chars > _MAX_BATCH_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += entry_chars

    if current:
        batches.append(current)
    return batches


def build_enrich_prompt(
    entries: list[EnrichEntry],
    backend: PromptBackend = PromptBackend.CLI,
) -> str:
    """Build the enrich prompt with articles embedded inline."""
    parts: list[str] = []
    for i, entry in enumerate(entries):
        text = entry.text[:_MAX_ARTICLE_CHARS]
        parts.append(f"{_ARTICLE_SEPARATOR}\n{i + 1}\n{entry.title}\n\n{text}")
    articles_block = "\n".join(parts)
    return render_prompt(
        RECAP_ENRICH_BATCH_PROMPT,
        backend,
        expected_count=str(len(entries)),
        articles_block=articles_block,
    )


def _parse_separated_chunks(chunks: list[str], valid_nums: set[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        if len(lines) < _MIN_CHUNK_LINES:
            continue
        num_idx = None
        for idx, line in enumerate(lines):
            if line.strip() in valid_nums:
                num_idx = idx
                break
        if num_idx is None:
            continue
        num = lines[num_idx].strip()
        headline = " ".join(line.strip() for line in lines[num_idx + 1 :] if line.strip())
        if headline:
            parsed[num] = headline
    return parsed


def _parse_consecutive_lines(lines: list[str], valid_nums: set[str]) -> dict[str, str]:
    """Parse ``NUMBER\\nHEADLINE`` pairs from consecutive lines."""
    parsed: dict[str, str] = {}
    i = 0
    while i < len(lines):
        num = lines[i].strip()
        if num in valid_nums and i + 1 < len(lines):
            headline_parts: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() not in valid_nums:
                part = lines[i].strip()
                if part:
                    headline_parts.append(part)
                i += 1
            headline = " ".join(headline_parts)
            if headline:
                parsed[num] = headline
        else:
            i += 1
    return parsed


def _parse_enrich_chunks(text: str, valid_nums: set[str]) -> dict[str, str]:
    """Parse ``NUMBER\\nHEADLINE`` pairs from agent output.

    Supports two formats:
    - Blank-line separated chunks (``NUMBER\\nHEADLINE\\n\\nNUMBER\\nHEADLINE``)
    - Consecutive lines (``NUMBER\\nHEADLINE\\nNUMBER\\nHEADLINE``)
    """
    chunks = re.split(r"\n\s*\n", text.strip())
    if len(chunks) > 1:
        return _parse_separated_chunks(chunks, valid_nums)
    return _parse_consecutive_lines(text.strip().splitlines(), valid_nums)


def parse_enrich_stdout(
    stdout_path: Path,
    entries: list[EnrichEntry],
) -> dict[str, str]:
    """Parse new headlines from agent stdout.

    Returns ``{article_id: new_title}``.
    Raises ``RecapPipelineError`` if recognition drops below 50%.
    """
    text = read_agent_stdout(stdout_path, "recap_enrich")
    valid_nums = {str(i + 1) for i in range(len(entries))}
    num_to_id = {str(i + 1): entries[i].article_id for i in range(len(entries))}

    parsed: dict[str, str] = _parse_enrich_chunks(text, valid_nums)

    recognition = len(parsed) / len(entries) if entries else 1.0
    if recognition < _MIN_RECOGNITION_RATE:
        raise RecapPipelineError(
            "recap_enrich",
            f"Agent enriched only {len(parsed)}/{len(entries)} articles ({recognition:.0%})",
        )
    if len(parsed) < len(entries):
        missing = [
            f"{i + 1} ({e.article_id})" for i, e in enumerate(entries) if str(i + 1) not in parsed
        ]
        logger.warning(
            "Enrich: %d/%d headlines recognised — missing: %s",
            len(parsed),
            len(entries),
            ", ".join(missing),
        )

    return {num_to_id[num]: title for num, title in parsed.items()}


# ---------------------------------------------------------------------------
# Task launchers
# ---------------------------------------------------------------------------


def _warn_unprocessed(
    logger: Any,
    step_name: str,
    entries: list[EnrichEntry],
    all_enriched: dict[str, str],
    total: int,
) -> None:
    remaining = [e for e in entries if e.article_id not in all_enriched]
    if remaining:
        logger.warning(
            "[cyan]%s:[/cyan] %d/%d articles still unprocessed after %d round(s)",
            step_name,
            len(remaining),
            total,
            _MAX_ROUNDS,
        )


def _run_enrich(
    ctx: FlowContext,
    *,
    step_name: str,
    entries: list[EnrichEntry],
) -> tuple[dict[str, str], bool]:
    """Batch articles, run agents, parse stdout for new headlines.

    Resources must already be loaded; callers pass ready ``EnrichEntry``
    objects.  Articles not processed by the agent are requeued for
    subsequent rounds (up to ``_MAX_ROUNDS``).  Partial agent output
    triggers requeue within our retry loop.

    Returns ``(enriched_dict, had_crash)``.  *enriched_dict* maps
    ``article_id → new_title``.  When *had_crash* is True the caller
    should persist partial results and stop the pipeline.
    """
    if not entries:
        logger.info("[cyan]%s:[/cyan] No articles to enrich", step_name)
        return {}, False

    remaining = list(entries)
    total = len(remaining)
    logger.info("[cyan]%s:[/cyan] %d articles to enrich", step_name, total)

    all_enriched: dict[str, str] = {}
    batch_counter = next_batch_number(ctx.pdir, step_name) - 1
    had_crash = False

    def prepare(batch: list[EnrichEntry], batch_num: int) -> str:
        prompt = build_enrich_prompt(batch, ctx.inp.prompt_backend)
        task_id = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name=step_name,
            batch=batch_num,
            prompt=prompt,
        )
        logger.info("[cyan]%s:[/cyan] Batch %d — %d articles", step_name, batch_num, len(batch))
        return task_id

    def parse(task_id: str, batch: list[EnrichEntry], _batch_num: int) -> dict[str, str]:
        stdout_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
        return parse_enrich_stdout(stdout_path, batch)

    for round_num in range(1, _MAX_ROUNDS + 1):
        if not remaining:
            break

        enriched_before = len(all_enriched)
        round_entries = list(remaining)
        batches = split_into_enrich_batches(round_entries)
        logger.info(
            "[cyan]%s:[/cyan] Round %d: %d articles -> %d batch(es)",
            step_name,
            round_num,
            len(round_entries),
            len(batches),
        )

        batch_results, n_failed, batch_counter = submit_and_collect(
            ctx,
            batches,
            step_name=step_name,
            step_label=f"{step_name} batch",
            start_batch=batch_counter,
            max_parallel=ctx.inp.effective_max_parallel(_MAX_PARALLEL),
            prepare_fn=prepare,
            parse_fn=parse,
            logger=logger,
        )

        for batch_result in batch_results:
            all_enriched.update(batch_result)

        if n_failed > 0:
            had_crash = True
            break

        remaining = [e for e in round_entries if e.article_id not in all_enriched]

        if remaining and len(all_enriched) == enriched_before:
            logger.warning(
                "[cyan]%s:[/cyan] No progress in round %d — stopping retries",
                step_name,
                round_num,
            )
            break

    if not had_crash:
        _warn_unprocessed(logger, step_name, entries, all_enriched, total)

    logger.info("[cyan]%s:[/cyan] %d/%d articles enriched", step_name, len(all_enriched), total)
    return all_enriched, had_crash


class Enrich(TaskLauncher):
    """Enrich articles flagged ``vague``/``follow`` by classify.

    ``LoadResources`` must run first — it populates ``enrich_ids`` with
    articles that have successfully loaded resources.
    """

    name = "enrich"

    def restore_state(self) -> None:
        """Reconstruct ``ctx.state["enriched_articles"]`` from persisted digest."""
        enriched: dict[str, str] = {}
        for a in self.ctx.digest.articles:
            if a.enriched_title:
                enriched[a.article_id] = a.enriched_title
        self.ctx.state["enriched_articles"] = enriched

    def execute(self) -> None:
        ctx = self.ctx
        enrich_ids: list[str] = ctx.state.get("enrich_ids", [])

        already_enriched = {a.article_id for a in ctx.digest.articles if a.enriched_title}
        remaining_ids = [sid for sid in enrich_ids if sid not in already_enriched]

        if already_enriched:
            logger.info(
                "[cyan]enrich:[/cyan] %d already enriched, %d remaining",
                len(already_enriched),
                len(remaining_ids),
            )

        prev_enriched: dict[str, str] = {
            a.article_id: a.enriched_title
            for a in ctx.digest.articles
            if a.article_id in already_enriched and a.enriched_title
        }

        if not remaining_ids:
            ctx.state["enriched_articles"] = prev_enriched
            return

        entries = _build_enrich_entries(ctx, remaining_ids)
        if not entries:
            logger.warning(
                "[cyan]enrich:[/cyan] No cached resources for %d remaining articles"
                " — marking incomplete",
                len(remaining_ids),
            )
            ctx.state["enriched_articles"] = prev_enriched
            self.fully_completed = False
            return

        new_enriched, had_crash = _run_enrich(ctx, step_name="recap_enrich", entries=entries)

        all_enriched = {**prev_enriched, **new_enriched}
        ctx.state["enriched_articles"] = all_enriched

        by_id = {a.article_id: a for a in ctx.digest.articles}
        for aid, new_title in new_enriched.items():
            if aid in by_id:
                by_id[aid].enriched_title = new_title

        if had_crash:
            self.fully_completed = False
            raise RecapPipelineError(
                "recap_enrich",
                f"batch failed ({len(new_enriched)}/{len(remaining_ids)} enriched)"
                " — see errors above",
            )

        if len(new_enriched) < len(remaining_ids):
            self.fully_completed = False


def _build_enrich_entries(
    ctx: FlowContext,
    article_ids: list[str],
) -> list[EnrichEntry]:
    """Build ``EnrichEntry`` objects by reading texts from ``ResourceCache``."""
    index_entries = [ctx.article_map[sid] for sid in article_ids if sid in ctx.article_map]
    if not index_entries:
        return []

    loaded = load_cached_resource_texts(
        index_entries,
        cache_dir=resource_cache_dir(ctx.inp.data_dir, ctx.inp.business_date),
        min_resource_chars=ctx.inp.min_resource_chars,
    )
    return [
        EnrichEntry(article_id=sid, title=title, text=text) for sid, (title, text) in loaded.items()
    ]
