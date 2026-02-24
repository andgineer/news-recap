"""Task launchers: enrich articles via LLM with loaded full-text resources.

* ``Enrich`` — enriches articles flagged by classify as needing more context.
* ``EnrichFull`` — deep-enriches articles from significant events, then
  builds event payloads for downstream synthesis.

Uses file-based I/O: each article is written as a separate file in
``input/articles/``, the agent writes rewritten files to ``output/articles/``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.storage.pipeline_io import (
    load_cached_resource_texts,
    load_resource_texts,
    materialize_step,
    next_batch_number,
)
from news_recap.recap.tasks.base import (
    FlowContext,
    PipelineStepResult,
    RecapPipelineError,
    TaskLauncher,
)
from news_recap.recap.tasks.prompts import RECAP_ENRICH_BATCH_PROMPT

logger = logging.getLogger(__name__)

MIN_ARTICLES_FOR_SIGNIFICANT_EVENT = 2

_MAX_BATCH = 10
_MIN_BATCH = 7
_MAX_ARTICLE_CHARS = 30_000
_MAX_ROUNDS = 3
_MAX_PARALLEL = 3

_ARTICLE_FILE_RE = re.compile(r"^(\d+)\.txt$")


# ---------------------------------------------------------------------------
# Batching / prompt / file I/O (enrich-specific)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EnrichEntry:
    """Article with loaded resource text ready for the enrich prompt."""

    article_id: str
    title: str
    text: str


def split_into_enrich_batches(entries: list[EnrichEntry]) -> list[list[EnrichEntry]]:
    """Split enrichment entries into evenly-sized batches.

    Maximizes parallelism (up to ``_MAX_PARALLEL`` batches) while keeping
    each batch between ``_MIN_BATCH`` and ``_MAX_BATCH`` articles.
    """
    if not entries:
        return []

    n = len(entries)
    min_batches = -(-n // _MAX_BATCH)
    max_batches = max(1, n // _MIN_BATCH)
    n_batches = max(min_batches, min(_MAX_PARALLEL, max_batches))

    base, extra = divmod(n, n_batches)
    batches: list[list[EnrichEntry]] = []
    start = 0
    for i in range(n_batches):
        size = base + (1 if i < extra else 0)
        batches.append(entries[start : start + size])
        start += size
    return batches


def build_enrich_prompt() -> str:
    """Return the static enrich prompt (no template variables)."""
    return RECAP_ENRICH_BATCH_PROMPT


def write_enrich_input_files(
    workdir: Path,
    entries: list[EnrichEntry],
) -> None:
    """Write each article as ``input/articles/N.txt`` in the task workdir."""
    articles_dir = workdir / "input" / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)
    (workdir / "output" / "articles").mkdir(parents=True, exist_ok=True)
    for i, entry in enumerate(entries):
        text = entry.text[:_MAX_ARTICLE_CHARS]
        content = f"{entry.title}\n\n{text}\n"
        (articles_dir / f"{i + 1}.txt").write_text(content, "utf-8")


def parse_enrich_output_files(
    workdir: Path,
    entries: list[EnrichEntry],
) -> dict[str, dict[str, str]]:
    """Parse enrichment results from ``output/articles/*.txt``.

    Each output file has: line 1 = new title, blank line, rest = excerpt.
    Returns ``{article_id: {new_title, clean_text}}``.
    """
    output_dir = workdir / "output" / "articles"
    if not output_dir.is_dir():
        logger.warning("Enrich output dir not found: %s", output_dir)
        return {}

    parsed: dict[str, dict[str, str]] = {}
    count = len(entries)

    for path in sorted(output_dir.iterdir()):
        m = _ARTICLE_FILE_RE.match(path.name)
        if not m:
            logger.warning("Skipping non-article file in output: %s", path.name)
            continue
        n = int(m.group(1))
        if n < 1 or n > count:
            logger.warning("Out-of-range article file: %s (expected 1..%d)", path.name, count)
            continue

        raw = path.read_text("utf-8").strip()
        blank_pos = raw.find("\n\n")
        if blank_pos < 0:
            logger.warning("No blank-line separator in %s — skipping", path.name)
            continue
        new_title = raw[:blank_pos].strip()
        clean_text = raw[blank_pos + 2 :].strip()
        if not new_title:
            logger.warning("Empty title in %s — skipping", path.name)
            continue
        if not clean_text:
            logger.warning("Empty excerpt in %s — skipping", path.name)
            continue

        aid = entries[n - 1].article_id
        parsed[aid] = {"new_title": new_title, "clean_text": clean_text}

    if entries and len(parsed) < len(entries):
        missing = [
            f"{i + 1} ({e.article_id})" for i, e in enumerate(entries) if e.article_id not in parsed
        ]
        logger.warning(
            "Batch enrich: %d/%d recognised — missing: %s",
            len(parsed),
            len(entries),
            ", ".join(missing),
        )

    return parsed


# ---------------------------------------------------------------------------
# Event helpers (used by EnrichFull and downstream tasks)
# ---------------------------------------------------------------------------


def select_significant_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter events to only significant ones (high/medium or multi-article)."""
    return [
        event
        for event in events
        if event.get("significance") in ("high", "medium")
        or len(event.get("article_ids", [])) >= MIN_ARTICLES_FOR_SIGNIFICANT_EVENT
    ]


def articles_needing_full_text(
    events: list[dict[str, Any]],
    article_map: dict[str, ArticleIndexEntry],
) -> list[ArticleIndexEntry]:
    """Collect unique articles from significant events for full-text loading."""
    seen: set[str] = set()
    result: list[ArticleIndexEntry] = []
    for event in events:
        for aid in event.get("article_ids", []):
            if aid not in seen and aid in article_map:
                seen.add(aid)
                result.append(article_map[aid])
    return result


def build_event_payloads(
    events: list[dict[str, Any]],
    enriched: dict[str, dict[str, str]],
    enriched_full: dict[str, dict[str, str]],
    article_map: dict[str, ArticleIndexEntry],
) -> list[dict[str, Any]]:
    """Merge enriched texts into event payloads for synthesis."""
    payloads: list[dict[str, Any]] = []
    for event in events:
        articles_data: list[dict[str, Any]] = []
        for aid in event.get("article_ids", []):
            entry = article_map.get(aid)
            if not entry:
                continue
            full = enriched_full.get(aid, {})
            partial = enriched.get(aid, {})
            text = full.get("clean_text") or partial.get("clean_text", "")
            title = full.get("new_title") or partial.get("new_title") or entry.title
            articles_data.append(
                {
                    "article_id": aid,
                    "title": title,
                    "url": entry.url,
                    "source": entry.source,
                    "text": text,
                },
            )
        payloads.append(
            {
                "event_id": event.get("event_id", ""),
                "title": event.get("title", ""),
                "significance": event.get("significance", "medium"),
                "articles": articles_data,
            },
        )
    return payloads


# ---------------------------------------------------------------------------
# Task launchers
# ---------------------------------------------------------------------------


def _run_enrich(
    ctx: FlowContext,
    *,
    step_name: str,
    entries: list[EnrichEntry],
) -> dict[str, dict[str, str]]:
    """Batch, write input files, run agents, parse output.

    Resources must already be loaded; callers pass ready ``EnrichEntry``
    objects.  Articles not processed by the agent are requeued for
    subsequent rounds (up to ``_MAX_ROUNDS``).  Agent crashes are retried
    by Prefect (``retries=2`` on ``run_ai_agent``); partial output
    triggers requeue within our retry loop.
    """
    pf_logger = get_run_logger()

    if not entries:
        pf_logger.info("[%s] No articles to enrich", step_name)
        return {}

    remaining = list(entries)
    total = len(remaining)
    pf_logger.info("[%s] %d articles to enrich", step_name, total)

    prompt = build_enrich_prompt()
    all_enriched: dict[str, dict[str, str]] = {}
    batch_counter = next_batch_number(ctx.pdir, step_name) - 1

    for round_num in range(1, _MAX_ROUNDS + 1):
        if not remaining:
            break

        enriched_before = len(all_enriched)
        batches = split_into_enrich_batches(remaining)
        pf_logger.info(
            "[%s] Round %d: %d articles -> %d batch(es)",
            step_name,
            round_num,
            len(remaining),
            len(batches),
        )
        remaining = []

        for window_start in range(0, len(batches), _MAX_PARALLEL):
            window = batches[window_start : window_start + _MAX_PARALLEL]

            futures: list[tuple[int, list[EnrichEntry], Any]] = []
            for batch in window:
                batch_counter += 1
                task_id = materialize_step(
                    ctx.workdir_mgr,
                    ctx.inp,
                    step_name=step_name,
                    batch=batch_counter,
                    prompt=prompt,
                )
                write_enrich_input_files(ctx.pdir / task_id, batch)
                pf_logger.info(
                    "[%s] Batch %d — %d articles",
                    step_name,
                    batch_counter,
                    len(batch),
                )
                future = run_ai_agent.with_options(task_run_name=task_id).submit(
                    pipeline_dir=str(ctx.pdir),
                    step_name=step_name,
                    task_id=task_id,
                )
                futures.append((batch_counter, batch, future))

            for batch_num, batch, future in futures:
                try:
                    tid = future.result()
                except RecapPipelineError as exc:
                    pf_logger.error("%s batch %d failed: %s", step_name, batch_num, exc)
                    ctx.result.steps.append(
                        PipelineStepResult(
                            f"{step_name} batch {batch_num}",
                            None,
                            "failed",
                        ),
                    )
                    continue

                batch_result = parse_enrich_output_files(ctx.pdir / tid, batch)
                all_enriched.update(batch_result)
                ctx.result.steps.append(
                    PipelineStepResult(
                        f"{step_name} batch {batch_num}",
                        tid,
                        "completed",
                    ),
                )
                remaining.extend(e for e in batch if e.article_id not in batch_result)

        if remaining and len(all_enriched) == enriched_before:
            pf_logger.warning(
                "[%s] No progress in round %d — stopping retries",
                step_name,
                round_num,
            )
            break

    if remaining:
        pf_logger.warning(
            "[%s] %d/%d articles still unprocessed after %d round(s)",
            step_name,
            len(remaining),
            total,
            _MAX_ROUNDS,
        )

    pf_logger.info("[%s] %d/%d articles enriched", step_name, len(all_enriched), total)
    return all_enriched


class Enrich(TaskLauncher):
    """Enrich articles flagged ``vague``/``follow`` by classify.

    ``LoadResources`` must run first — it populates ``enrich_ids`` with
    articles that have successfully loaded resources.
    """

    name = "enrich"

    def restore_state(self) -> None:
        """Reconstruct ``ctx.state["enriched_articles"]`` from persisted digest."""
        enriched: dict[str, dict[str, str]] = {}
        for a in self.ctx.digest.articles:
            if a.enriched_title and a.enriched_text:
                enriched[a.article_id] = {
                    "new_title": a.enriched_title,
                    "clean_text": a.enriched_text,
                }
        self.ctx.state["enriched_articles"] = enriched

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        enrich_ids: list[str] = ctx.state.get("enrich_ids", [])

        already_enriched = {
            a.article_id for a in ctx.digest.articles if a.enriched_title and a.enriched_text
        }
        remaining_ids = [sid for sid in enrich_ids if sid not in already_enriched]

        if already_enriched:
            pf_logger.info(
                "[enrich] %d already enriched, %d remaining",
                len(already_enriched),
                len(remaining_ids),
            )

        prev_enriched: dict[str, dict[str, str]] = {
            a.article_id: {"new_title": a.enriched_title, "clean_text": a.enriched_text}
            for a in ctx.digest.articles
            if a.article_id in already_enriched and a.enriched_title and a.enriched_text
        }

        if not remaining_ids:
            ctx.state["enriched_articles"] = prev_enriched
            return

        entries = _build_enrich_entries(ctx, remaining_ids)
        if not entries:
            pf_logger.warning(
                "[enrich] No cached resources for %d remaining articles — marking incomplete",
                len(remaining_ids),
            )
            ctx.state["enriched_articles"] = prev_enriched
            self.fully_completed = False
            return

        new_enriched = _run_enrich(ctx, step_name="recap_enrich", entries=entries)

        all_enriched = {**prev_enriched, **new_enriched}
        ctx.state["enriched_articles"] = all_enriched

        by_id = {a.article_id: a for a in ctx.digest.articles}
        for aid, data in new_enriched.items():
            if aid in by_id:
                by_id[aid].enriched_title = data.get("new_title")
                by_id[aid].enriched_text = data.get("clean_text")

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
        cache_dir=ctx.pdir,
        min_resource_chars=ctx.inp.min_resource_chars,
    )
    return [
        EnrichEntry(article_id=sid, title=title, text=text) for sid, (title, text) in loaded.items()
    ]


def _load_and_build_entries(
    ctx: FlowContext,
    index_entries: list[ArticleIndexEntry],
) -> list[EnrichEntry]:
    """Fetch resources over the network (with cache) and build ``EnrichEntry`` objects.

    Unlike ``_build_enrich_entries`` (cache-only), this performs actual HTTP
    fetches for articles not yet cached.  Used by ``EnrichFull`` which
    operates on a different article set than ``LoadResources``.
    """
    if not index_entries:
        return []
    loaded = load_resource_texts(
        index_entries,
        cache_dir=ctx.pdir,
        min_resource_chars=ctx.inp.min_resource_chars,
    )
    return [
        EnrichEntry(article_id=sid, title=title, text=text) for sid, (title, text) in loaded.items()
    ]


class EnrichFull(TaskLauncher):
    """Select significant events, load full article text, and enrich via LLM."""

    name = "enrich_full"

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        events: list[dict[str, Any]] = ctx.state["events"]
        enriched_articles: dict[str, dict[str, str]] = ctx.state.get("enriched_articles", {})

        significant = select_significant_events(events)
        articles_for_full = articles_needing_full_text(significant, ctx.article_map)
        pf_logger.info(
            "Significant events: %d, articles needing full text: %d",
            len(significant),
            len(articles_for_full),
        )

        entries = _load_and_build_entries(ctx, articles_for_full)
        enriched_full = _run_enrich(ctx, step_name="recap_enrich_full", entries=entries)

        ctx.state["event_payloads"] = build_event_payloads(
            events,
            enriched_articles,
            enriched_full,
            ctx.article_map,
        )
