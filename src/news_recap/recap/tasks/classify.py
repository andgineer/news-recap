"""Task launcher: batch-classify articles into ok / enrich / trash."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from prefect.logging import get_run_logger

from news_recap.recap.agents.ai_agent import run_ai_agent
from news_recap.recap.models import DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import materialize_step
from news_recap.recap.tasks.base import (
    PipelineStepResult,
    RecapPipelineError,
    TaskLauncher,
)
from news_recap.recap.tasks.prompts import RECAP_CLASSIFY_BATCH_PROMPT

logger = logging.getLogger(__name__)

_MIN_BATCH_SUCCESS_RATE = 0.8

_MAX_PROMPT_CHARS = 60_000
_MIN_BATCH = 50
_MAX_BATCH = 500
_MIN_RECOGNITION_RATE = 0.8


# ---------------------------------------------------------------------------
# Batching / prompt / parse (classify-specific)
# ---------------------------------------------------------------------------


def split_into_classify_batches(
    entries: list[DigestArticle],
    preferences: UserPreferences,
) -> list[list[DigestArticle]]:
    """Split entries into char-budget-aware batches for batch classify.

    Packs headlines greedily up to ``_MAX_PROMPT_CHARS`` total chars
    or ``_MAX_BATCH`` entries per batch.  A trailing batch smaller
    than ``_MIN_BATCH`` is merged into the previous one.

    >>> from news_recap.recap.models import DigestArticle, UserPreferences
    >>> prefs = UserPreferences()
    >>> entries = [
    ...     DigestArticle(
    ...         article_id=str(i), title=f"T{i}",
    ...         url="u", source="s", published_at="2026-01-01T00:00:00+00:00",
    ...         clean_text="",
    ...     )
    ...     for i in range(10)
    ... ]
    >>> batches = split_into_classify_batches(entries, prefs)
    >>> len(batches) >= 1
    True
    """
    if not entries:
        return []

    preamble_len = len(
        RECAP_CLASSIFY_BATCH_PROMPT.format(
            discard_policy=preferences.not_interesting or "none",
            priority_policy=preferences.interesting or "none",
            expected_count=0,
            headlines_block="",
        ),
    )
    budget = max(1, _MAX_PROMPT_CHARS - preamble_len)

    batches: list[list[DigestArticle]] = []
    current: list[DigestArticle] = []
    current_chars = 0

    for idx, entry in enumerate(entries):
        line = f"{idx + 1}\t{entry.title}\n"
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


def build_classify_batch_prompt(
    entries: list[DigestArticle],
    preferences: UserPreferences,
) -> str:
    """Build the inline batch classify prompt for a slice of articles.

    Uses sequential 1-based numbers as IDs (not UUIDs) — short numbers are
    unambiguous and agents reproduce them reliably.
    """
    headlines_block = "\n".join(f"{i + 1}\t{e.title}" for i, e in enumerate(entries))
    return RECAP_CLASSIFY_BATCH_PROMPT.format(
        discard_policy=preferences.not_interesting or "none",
        priority_policy=preferences.interesting or "none",
        expected_count=len(entries),
        headlines_block=headlines_block,
    )


def parse_classify_batch_stdout(  # noqa: C901, PLR0912
    stdout_path: Path,
    entries: list[DigestArticle],
) -> tuple[list[str], list[str]]:
    """Parse batch classification verdicts from agent stdout log.

    Each verdict line: ``N<TAB>(ok|enrich|trash)``.
    Sets ``entry.verdict`` on each ``DigestArticle``.
    Returns ``(kept_ids, enrich_ids)``.
    """
    if not stdout_path.exists():
        logger.warning("Verdicts file not found: %s — defaulting all to ok", stdout_path)
        return [e.article_id for e in entries], []

    text = stdout_path.read_text("utf-8")

    begin_idx = text.find("BEGIN_VERDICTS")
    end_idx = text.find("END_VERDICTS")
    if begin_idx != -1 and end_idx != -1 and end_idx > begin_idx:
        verdicts_text = text[begin_idx + len("BEGIN_VERDICTS") : end_idx]
    else:
        verdicts_text = text

    valid_nums = {str(i + 1) for i in range(len(entries))}

    parsed: dict[str, str] = {}
    for raw_line in verdicts_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:  # noqa: PLR2004
            parts = line.split(None, 1)
        if len(parts) != 2:  # noqa: PLR2004
            continue
        num, verdict = parts[0].strip(), parts[1].strip().lower()
        if num not in valid_nums or verdict not in ("ok", "enrich", "trash"):
            continue
        parsed[num] = verdict

    recognition_rate = len(parsed) / len(entries) if entries else 1.0
    if recognition_rate < _MIN_RECOGNITION_RATE:
        raise RecapPipelineError(
            "recap_classify",
            f"Agent classified only {len(parsed)}/{len(entries)} articles ({recognition_rate:.0%})",
        )
    if recognition_rate < 1.0:
        logger.warning(
            "Batch classify: %d/%d verdicts recognised — missing IDs default to ok",
            len(parsed),
            len(entries),
        )

    kept: list[str] = []
    enrich: list[str] = []
    for i, e in enumerate(entries):
        verdict = parsed.get(str(i + 1), "ok")
        e.verdict = verdict
        if verdict == "trash":
            continue
        kept.append(e.article_id)
        if verdict == "enrich":
            enrich.append(e.article_id)

    return kept, enrich


# ---------------------------------------------------------------------------
# Task launcher
# ---------------------------------------------------------------------------


class Classify(TaskLauncher):
    """Split articles into batches and ask the LLM to verdict each as ok / enrich / trash."""

    name = "classify"

    def restore_state(self) -> None:
        """Reconstruct kept_entries and enrich_ids from digest verdicts."""
        ctx = self.ctx
        kept = []
        enrich_ids = []
        for a in ctx.digest.articles:
            if a.verdict == "trash":
                continue
            if a.article_id in ctx.article_map:
                kept.append(ctx.article_map[a.article_id])
            if a.verdict == "enrich":
                enrich_ids.append(a.article_id)
        ctx.state["kept_entries"] = kept
        ctx.state["enrich_ids"] = enrich_ids

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        batches = split_into_classify_batches(ctx.inp.articles, ctx.inp.preferences)
        debug_max = int(os.getenv("NEWS_RECAP_CLASSIFY_MAX_BATCHES", "0")) or None
        if debug_max:
            batches = batches[:debug_max]
        n_batches = len(batches)
        pf_logger.info("[classify] %d articles -> %d batch(es)", len(ctx.inp.articles), n_batches)

        futures: list[tuple[int, list[Any], Any]] = []
        for i, batch in enumerate(batches):
            prompt = build_classify_batch_prompt(batch, ctx.inp.preferences)
            task_id = materialize_step(
                ctx.workdir_mgr,
                ctx.inp,
                step_name="recap_classify",
                batch=i + 1,
                prompt=prompt,
            )
            pf_logger.info("[classify] Batch %d/%d — %d headlines", i + 1, n_batches, len(batch))
            future = run_ai_agent.with_options(task_run_name=task_id).submit(
                pipeline_dir=str(ctx.pdir),
                step_name="recap_classify",
                task_id=task_id,
            )
            futures.append((i, batch, future))

        all_kept: list[str] = []
        all_enrich: list[str] = []
        failed_batches = 0
        for i, batch, future in futures:
            try:
                tid = future.result()
            except RecapPipelineError as exc:
                pf_logger.error("classify batch %d failed: %s", i + 1, exc)
                failed_batches += 1
                ctx.result.steps.append(
                    PipelineStepResult(f"classify batch {i + 1}", None, "failed"),
                )
                continue
            verdicts_path = ctx.pdir / tid / "output" / "agent_stdout.log"
            kept, enrich = parse_classify_batch_stdout(verdicts_path, batch)
            all_kept.extend(kept)
            all_enrich.extend(enrich)
            ctx.result.steps.append(
                PipelineStepResult(f"classify batch {i + 1}", tid, "completed"),
            )

        if failed_batches > 0:
            success_rate = (n_batches - failed_batches) / n_batches
            if success_rate < _MIN_BATCH_SUCCESS_RATE:
                raise RecapPipelineError(
                    "recap_classify",
                    f"Too many batch failures: {failed_batches}/{n_batches} failed",
                )
            pf_logger.warning(
                "[classify] %d/%d batches failed — partial results",
                failed_batches,
                n_batches,
            )

        ctx.state["kept_entries"] = [
            ctx.article_map[sid] for sid in all_kept if sid in ctx.article_map
        ]
        ctx.state["enrich_ids"] = all_enrich
        pf_logger.info(
            "Classify: %d kept, %d discarded, %d need enrichment",
            len(all_kept),
            len(ctx.inp.articles) - len(all_kept),
            len(all_enrich),
        )
