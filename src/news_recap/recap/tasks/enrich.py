"""Task launchers: enrich articles via LLM with loaded full-text resources.

* ``Enrich`` — enriches articles flagged by classify as needing more context.
* ``EnrichFull`` — deep-enriches articles from significant events, then
  builds event payloads for downstream synthesis.

Uses the same batch/stdout pattern as Classify: article text is embedded in
the prompt, the agent prints tab-separated results to stdout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.storage.pipeline_io import load_resource_texts, materialize_step
from news_recap.recap.tasks.base import (
    FlowContext,
    PipelineStepResult,
    RecapPipelineError,
    TaskLauncher,
)
from news_recap.recap.tasks.prompts import RECAP_ENRICH_BATCH_PROMPT

logger = logging.getLogger(__name__)

MIN_ARTICLES_FOR_SIGNIFICANT_EVENT = 2

_MAX_PROMPT_CHARS = 100_000
_MAX_BATCH = 20
_MIN_BATCH = 3
_MIN_RECOGNITION_RATE = 0.5
_MAX_ARTICLE_CHARS = 8_000


# ---------------------------------------------------------------------------
# Batching / prompt / parse (enrich-specific)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EnrichEntry:
    """Article with loaded resource text ready for the enrich prompt."""

    article_id: str
    title: str
    text: str


def split_into_enrich_batches(entries: list[EnrichEntry]) -> list[list[EnrichEntry]]:
    """Split enrichment entries into char-budget-aware batches."""
    if not entries:
        return []

    preamble_len = len(
        RECAP_ENRICH_BATCH_PROMPT.format(expected_count=0, articles_block=""),
    )
    budget = max(1, _MAX_PROMPT_CHARS - preamble_len)

    batches: list[list[EnrichEntry]] = []
    current: list[EnrichEntry] = []
    current_chars = 0

    for entry in entries:
        text = entry.text[:_MAX_ARTICLE_CHARS]
        line = f"0\t{entry.title}\t{text}\n"
        line_chars = len(line)
        over_budget = current_chars + line_chars > budget
        over_max = len(current) >= _MAX_BATCH
        if current and (over_budget or over_max):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += line_chars

    if current:
        batches.append(current)

    if len(batches) >= 2 and len(batches[-1]) < _MIN_BATCH:  # noqa: PLR2004
        batches[-2].extend(batches.pop())

    return batches


def build_enrich_batch_prompt(entries: list[EnrichEntry]) -> str:
    """Build inline enrich prompt with article text embedded."""
    lines: list[str] = []
    for i, e in enumerate(entries):
        text = e.text[:_MAX_ARTICLE_CHARS].replace("\n", " ").replace("\t", " ")
        lines.append(f"{i + 1}\t{e.title}\t{text}")
    articles_block = "\n".join(lines)
    return RECAP_ENRICH_BATCH_PROMPT.format(
        expected_count=len(entries),
        articles_block=articles_block,
    )


def parse_enrich_batch_stdout(
    stdout_path: Path,
    entries: list[EnrichEntry],
) -> dict[str, dict[str, str]]:
    """Parse batch enrichment results from agent stdout.

    Each output line: ``N<TAB>new_title<TAB>clean_text``.
    Returns ``{article_id: {new_title, clean_text}}``.
    """
    if not stdout_path.exists():
        logger.warning("Enrich stdout not found: %s", stdout_path)
        return {}

    text = stdout_path.read_text("utf-8")
    valid_nums = {str(i + 1) for i in range(len(entries))}

    parsed: dict[str, dict[str, str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:  # noqa: PLR2004
            continue
        num = parts[0].strip()
        if num not in valid_nums:
            continue
        idx = int(num) - 1
        aid = entries[idx].article_id
        parsed[aid] = {
            "new_title": parts[1].strip(),
            "clean_text": parts[2].strip(),
        }

    recognition_rate = len(parsed) / len(entries) if entries else 1.0
    if recognition_rate < _MIN_RECOGNITION_RATE:
        raise RecapPipelineError(
            "recap_enrich",
            f"Agent enriched only {len(parsed)}/{len(entries)} ({recognition_rate:.0%})",
        )
    if recognition_rate < 1.0:
        logger.warning(
            "Batch enrich: %d/%d recognised — missing articles skipped",
            len(parsed),
            len(entries),
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
    resource_entries: list[ArticleIndexEntry],
) -> dict[str, dict[str, str]]:
    """Shared enrichment: load resources, batch, run agent, parse stdout."""
    pf_logger = get_run_logger()
    loaded = load_resource_texts(
        resource_entries,
        cache_dir=ctx.pdir,
        min_resource_chars=ctx.inp.min_resource_chars,
    )

    if not loaded:
        pf_logger.info("[%s] No resources loaded — skipping agent call", step_name)
        return {}

    enrich_entries = [
        EnrichEntry(article_id=sid, title=title, text=text) for sid, (title, text) in loaded.items()
    ]
    batches = split_into_enrich_batches(enrich_entries)
    n_batches = len(batches)
    pf_logger.info(
        "[%s] %d articles -> %d batch(es)",
        step_name,
        len(enrich_entries),
        n_batches,
    )

    all_enriched: dict[str, dict[str, str]] = {}
    failed_batches = 0
    for i, batch in enumerate(batches):
        prompt = build_enrich_batch_prompt(batch)
        task_id = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name=step_name,
            batch=i + 1,
            prompt=prompt,
        )
        pf_logger.info("[%s] Batch %d/%d — %d articles", step_name, i + 1, n_batches, len(batch))
        try:
            tid = run_ai_agent.with_options(task_run_name=task_id)(
                pipeline_dir=str(ctx.pdir),
                step_name=step_name,
                task_id=task_id,
            )
        except RecapPipelineError as exc:
            pf_logger.error("%s batch %d failed: %s", step_name, i + 1, exc)
            failed_batches += 1
            ctx.result.steps.append(
                PipelineStepResult(f"{step_name} batch {i + 1}", None, "failed"),
            )
            continue
        stdout_path = ctx.pdir / tid / "output" / "agent_stdout.log"
        batch_result = parse_enrich_batch_stdout(stdout_path, batch)
        all_enriched.update(batch_result)
        ctx.result.steps.append(
            PipelineStepResult(f"{step_name} batch {i + 1}", tid, "completed"),
        )

    if failed_batches > 0:
        pf_logger.warning(
            "[%s] %d/%d batches failed — partial results",
            step_name,
            failed_batches,
            n_batches,
        )

    pf_logger.info("[%s] %d articles enriched", step_name, len(all_enriched))
    return all_enriched


class Enrich(TaskLauncher):
    """Fetch full text for articles flagged ``enrich`` by classify and re-run them."""

    name = "enrich"

    def execute(self) -> None:
        ctx = self.ctx
        enrich_ids: list[str] = ctx.state.get("enrich_ids", [])
        resource_entries = [ctx.article_map[sid] for sid in enrich_ids if sid in ctx.article_map]

        ctx.state["enriched_articles"] = _run_enrich(
            ctx,
            step_name="recap_enrich",
            resource_entries=resource_entries,
        )


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

        enriched_full = _run_enrich(
            ctx,
            step_name="recap_enrich_full",
            resource_entries=articles_for_full,
        )

        ctx.state["event_payloads"] = build_event_payloads(
            events,
            enriched_articles,
            enriched_full,
            ctx.article_map,
        )
