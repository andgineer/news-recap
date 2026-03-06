"""Task launcher: batch-classify articles into ok / vague / exclude."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from news_recap.recap.models import DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import materialize_step, next_batch_number
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
    read_agent_stdout,
)
from news_recap.recap.tasks.parallel import submit_and_collect
from news_recap.recap.tasks.prompts import RECAP_CLASSIFY_BATCH_PROMPT

logger = logging.getLogger(__name__)

_MAX_PROMPT_CHARS = 60_000
_MIN_BATCH = 50
_MAX_BATCH = 300
_MAX_PARALLEL = 3
_MIN_RECOGNITION_RATE = 0.8


# ---------------------------------------------------------------------------
# Batching / prompt / parse (classify-specific)
# ---------------------------------------------------------------------------


def split_into_classify_batches(
    entries: list[DigestArticle],
    preferences: UserPreferences,
) -> list[list[DigestArticle]]:
    """Split entries into evenly-sized batches for parallel classify.

    Maximizes parallelism (up to ``_MAX_PARALLEL`` batches) while keeping
    each batch between ``_MIN_BATCH`` and ``_MAX_BATCH`` articles.
    A char-budget safety check may produce extra splits when headlines
    are unusually long.

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

    n = len(entries)
    min_batches = -(-n // _MAX_BATCH)
    max_batches = max(1, n // _MIN_BATCH)
    n_batches = max(min_batches, min(_MAX_PARALLEL, max_batches))
    effective_max = -(-n // n_batches)

    preamble_len = len(
        RECAP_CLASSIFY_BATCH_PROMPT.format(
            exclude_policy=preferences.exclude or "none",
            expected_count=0,
            headlines_block="",
        ),
    )
    budget = max(1, _MAX_PROMPT_CHARS - preamble_len)

    batches: list[list[DigestArticle]] = []
    current: list[DigestArticle] = []
    current_chars = 0

    for idx, entry in enumerate(entries):
        line = f"{idx + 1}: {entry.title}\n"
        line_chars = len(line)
        over_budget = current_chars + line_chars > budget
        over_max = len(current) >= effective_max
        if current and (over_budget or over_max):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += line_chars

    if current:
        batches.append(current)

    return batches


def build_classify_batch_prompt(
    entries: list[DigestArticle],
    preferences: UserPreferences,
) -> str:
    """Build the inline batch classify prompt for a slice of articles.

    Uses sequential 1-based numbers as IDs (not UUIDs) — short numbers are
    unambiguous and agents reproduce them reliably.
    """
    headlines_block = "\n".join(f"{i + 1}: {e.title}" for i, e in enumerate(entries))
    return RECAP_CLASSIFY_BATCH_PROMPT.format(
        exclude_policy=preferences.exclude or "none",
        expected_count=len(entries),
        headlines_block=headlines_block,
    )


_VALID_VERDICTS = {"ok", "vague", "exclude"}


def _parse_verdict_line(line: str) -> tuple[str, str] | None:
    """Extract ``(number, verdict)`` from a stdout line.

    Accepts both ``NUMBER: VERDICT`` and ``NUMBER<TAB>VERDICT`` formats.
    """
    for sep in (":", "\t"):
        if sep in line:
            parts = line.split(sep, 1)
            num, verdict = parts[0].strip(), parts[1].strip().lower()
            if verdict in _VALID_VERDICTS:
                return num, verdict
            break
    parts = line.split(None, 1)
    if len(parts) == 2:  # noqa: PLR2004
        num, verdict = parts[0].strip(), parts[1].strip().lower()
        if verdict in _VALID_VERDICTS:
            return num, verdict
    return None


def _extract_verdicts(text: str, valid_nums: set[str]) -> dict[str, str]:
    """Parse verdict lines from agent output, optionally delimited by markers."""
    begin_idx = text.find("BEGIN_VERDICTS")
    end_idx = text.find("END_VERDICTS")
    if begin_idx != -1 and end_idx != -1 and end_idx > begin_idx:
        text = text[begin_idx + len("BEGIN_VERDICTS") : end_idx]

    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        result = _parse_verdict_line(line)
        if result is not None and result[0] in valid_nums:
            parsed[result[0]] = result[1]
    return parsed


def parse_classify_batch_stdout(
    stdout_path: Path,
    entries: list[DigestArticle],
) -> tuple[list[str], list[str]]:
    """Parse batch classification verdicts from agent stdout log.

    Each verdict line: ``N: ok|vague|exclude``.
    Sets ``entry.verdict`` on each ``DigestArticle``.
    Returns ``(kept_ids, enrich_ids)`` — ``exclude`` articles are dropped;
    ``ok`` articles are kept; ``vague`` articles are kept and sent to enrichment.
    """
    text = read_agent_stdout(stdout_path, "recap_classify")
    valid_nums = {str(i + 1) for i in range(len(entries))}
    parsed = _extract_verdicts(text, valid_nums)

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
        if verdict == "exclude":
            continue
        kept.append(e.article_id)
        if verdict == "vague":
            enrich.append(e.article_id)

    return kept, enrich


# ---------------------------------------------------------------------------
# Task launcher
# ---------------------------------------------------------------------------


class Classify(TaskLauncher):
    """Batch-classify articles as ok / vague / exclude."""

    name = "classify"

    def restore_state(self) -> None:
        """Reconstruct kept_entries and enrich_ids from digest verdicts."""
        ctx = self.ctx
        kept = []
        enrich_ids = []
        for a in ctx.digest.articles:
            if a.verdict in ("ok", "vague") and a.article_id in ctx.article_map:
                kept.append(ctx.article_map[a.article_id])
                if a.verdict == "vague":
                    enrich_ids.append(a.article_id)
        ctx.state["kept_entries"] = kept
        ctx.state["enrich_ids"] = enrich_ids

    def execute(self) -> None:
        ctx = self.ctx
        already_classified = {a.article_id for a in ctx.digest.articles if a.verdict is not None}
        to_classify = [a for a in ctx.inp.articles if a.article_id not in already_classified]

        if already_classified:
            logger.info(
                "[classify] %d already classified, %d remaining",
                len(already_classified),
                len(to_classify),
            )

        if not to_classify:
            self.restore_state()
            return

        batches = split_into_classify_batches(to_classify, ctx.inp.preferences)
        debug_max = int(os.getenv("NEWS_RECAP_CLASSIFY_MAX_BATCHES", "0")) or None
        if debug_max:
            batches = batches[:debug_max]
        logger.info("[classify] %d articles -> %d batch(es)", len(to_classify), len(batches))

        def prepare(batch: list[DigestArticle], batch_num: int) -> str:
            prompt = build_classify_batch_prompt(batch, ctx.inp.preferences)
            task_id = materialize_step(
                ctx.workdir_mgr,
                ctx.inp,
                step_name="recap_classify",
                batch=batch_num,
                prompt=prompt,
            )
            logger.info("[classify] Batch %d — %d headlines", batch_num, len(batch))
            return task_id

        def parse(task_id: str, batch: list[DigestArticle], _batch_num: int) -> None:
            verdicts_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
            parse_classify_batch_stdout(verdicts_path, batch)

        _, n_failed, _ = submit_and_collect(
            ctx,
            batches,
            step_name="recap_classify",
            step_label="classify batch",
            start_batch=next_batch_number(ctx.pdir, "recap_classify") - 1,
            max_parallel=ctx.inp.effective_max_parallel(_MAX_PARALLEL),
            prepare_fn=prepare,
            parse_fn=parse,
            logger=logger,
        )

        self._sync_verdicts(to_classify, logger)

        if n_failed > 0:
            self.fully_completed = False
            raise RecapPipelineError(
                "recap_classify",
                f"{n_failed}/{len(batches)} batch(es) failed — see errors above",
            )

        unclassified = sum(1 for a in ctx.digest.articles if a.verdict is None)
        if unclassified > 0:
            self.fully_completed = False

    def _sync_verdicts(self, to_classify: list[DigestArticle], logger: Any) -> None:
        """Sync new verdicts into digest and update state."""
        ctx = self.ctx
        digest_by_id = {a.article_id: a for a in ctx.digest.articles}
        for a in to_classify:
            if a.verdict is not None and a.article_id in digest_by_id:
                digest_by_id[a.article_id].verdict = a.verdict

        all_kept = [a.article_id for a in ctx.digest.articles if a.verdict in ("ok", "vague")]
        vague_ids = [a.article_id for a in ctx.digest.articles if a.verdict == "vague"]

        ctx.state["kept_entries"] = [
            ctx.article_map[sid] for sid in all_kept if sid in ctx.article_map
        ]
        ctx.state["enrich_ids"] = vague_ids

        logger.info(
            "Classify: %d kept (%d vague for enrichment), %d discarded",
            len(all_kept),
            len(vague_ids),
            len(ctx.inp.articles) - len(all_kept),
        )
