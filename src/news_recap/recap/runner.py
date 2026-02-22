"""Data-transformation helpers and shared types for the recap pipeline.

Business logic (article parsing, event building, etc.) used by the
recap flow modules.  All orchestration goes through Prefect.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from news_recap.brain.contracts import ArticleIndexEntry
from news_recap.brain.models import SourceCorpusEntry
from news_recap.brain.routing import RoutingDefaults
from news_recap.config import Settings
from news_recap.recap.prompts import RECAP_CLASSIFY_BATCH_PROMPT

logger = logging.getLogger(__name__)

MIN_ARTICLES_FOR_SIGNIFICANT_EVENT = 2

_DEFAULT_NOT_INTERESTING = "horoscopes, medical advice, sports (except Russia), Epstein files"
_DEFAULT_INTERESTING = "Russia, Serbia, war in Ukraine"

_CLASSIFY_MAX_PROMPT_CHARS = 60_000
_CLASSIFY_MIN_BATCH = 50
_CLASSIFY_MAX_BATCH = 500
_CLASSIFY_MIN_RECOGNITION_RATE = 0.8


@dataclass(slots=True)
class UserPreferences:
    """User preferences for digest composition."""

    max_headline_chars: int = 120
    interesting: str = _DEFAULT_INTERESTING
    not_interesting: str = _DEFAULT_NOT_INTERESTING
    language: str = "ru"

    def format_for_prompt(self) -> str:
        parts: list[str] = []
        if self.not_interesting:
            parts.append(f"DISCARD these topics (always trash): {self.not_interesting}")
        if self.interesting:
            parts.append(
                f"PRIORITY topics (user wants extra detail): {self.interesting}",
            )
        return "\n".join(parts) if parts else "no specific preferences"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_headline_chars": self.max_headline_chars,
            "interesting": self.interesting,
            "not_interesting": self.not_interesting,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPreferences:
        return cls(
            max_headline_chars=int(data.get("max_headline_chars", 120)),
            interesting=str(data.get("interesting", _DEFAULT_INTERESTING)),
            not_interesting=str(data.get("not_interesting", _DEFAULT_NOT_INTERESTING)),
            language=str(data.get("language", "ru")),
        )


@dataclass(slots=True)
class PipelineStepResult:
    """Result of a single pipeline step."""

    step_name: str
    task_id: str | None
    status: str
    error: str | None = None


@dataclass(slots=True)
class PipelineRunResult:
    """Result of a complete pipeline run."""

    pipeline_id: str
    business_date: date
    steps: list[PipelineStepResult] = field(default_factory=list)
    digest: dict[str, Any] | None = None
    status: str = "running"
    error: str | None = None


class RecapPipelineError(RuntimeError):
    """Pipeline step failure."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"Step {step} failed: {message}")
        self.step = step


# ---------------------------------------------------------------------------
# Article / event helpers (reused by the flow module)
# ---------------------------------------------------------------------------


def to_article_index(entries: list[SourceCorpusEntry]) -> list[ArticleIndexEntry]:
    return [
        ArticleIndexEntry(
            source_id=e.source_id,
            title=e.title,
            url=e.url,
            source=e.source,
            published_at=e.published_at.isoformat(),
        )
        for e in entries
    ]


def _safe_file_id(source_id: str) -> str:
    """Turn source_id into a filesystem-safe string."""
    return source_id.replace(":", "_").replace("/", "_")


def articles_to_individual_files(
    entries: list[SourceCorpusEntry],
) -> dict[str, bytes | str]:
    """One ``{id}_in.txt`` per article containing only the headline."""
    files: dict[str, bytes | str] = {}
    for e in entries:
        fid = _safe_file_id(e.source_id)
        files[f"{fid}_in.txt"] = e.title
    return files


def parse_classify_out_files(
    results_dir: Path,
    entries: list[SourceCorpusEntry],
) -> tuple[list[str], list[str]]:
    """Read ``{id}_out.txt`` files written by the agent.

    Each file contains a single word: ``ok``, ``enrich``, or ``trash``.
    Returns (kept_ids, enrich_ids).  ``ok`` and ``enrich`` are both kept.
    """
    kept: list[str] = []
    enrich: list[str] = []
    for e in entries:
        fid = _safe_file_id(e.source_id)
        out_path = results_dir / f"{fid}_out.txt"
        if not out_path.exists():
            kept.append(e.source_id)
            continue
        verdict = out_path.read_text("utf-8").strip().lower()
        if verdict == "trash":
            continue
        kept.append(e.source_id)
        if verdict == "enrich":
            enrich.append(e.source_id)
    return kept, enrich


def split_into_classify_batches(
    entries: list[SourceCorpusEntry],
    preferences: UserPreferences,
) -> list[list[SourceCorpusEntry]]:
    """Split entries into char-budget-aware batches for batch classify.

    Packs headlines greedily up to ``_CLASSIFY_MAX_PROMPT_CHARS`` total chars
    or ``_CLASSIFY_MAX_BATCH`` entries per batch.  A trailing batch smaller
    than ``_CLASSIFY_MIN_BATCH`` is merged into the previous one.

    >>> from datetime import UTC, datetime
    >>> from news_recap.brain.models import SourceCorpusEntry
    >>> prefs = UserPreferences()
    >>> entries = [
    ...     SourceCorpusEntry(
    ...         source_id=str(i), article_id=str(i), title=f"T{i}",
    ...         url="u", source="s", published_at=datetime.now(tz=UTC),
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
    budget = max(1, _CLASSIFY_MAX_PROMPT_CHARS - preamble_len)

    batches: list[list[SourceCorpusEntry]] = []
    current: list[SourceCorpusEntry] = []
    current_chars = 0

    for idx, entry in enumerate(entries):
        line = f"{idx + 1}\t{entry.title}\n"
        line_chars = len(line)
        over_budget = current_chars + line_chars > budget
        over_max = len(current) >= _CLASSIFY_MAX_BATCH
        if current and (over_budget or over_max):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += line_chars

    if current:
        batches.append(current)

    # Merge a too-small trailing batch into the previous
    if len(batches) >= 2 and len(batches[-1]) < _CLASSIFY_MIN_BATCH:  # noqa: PLR2004
        batches[-2].extend(batches.pop())

    return batches


def build_classify_batch_prompt(
    entries: list[SourceCorpusEntry],
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
    entries: list[SourceCorpusEntry],
) -> tuple[list[str], list[str]]:
    """Parse batch classification verdicts from agent stdout log.

    Reads from ``output/agent_stdout.log`` (the agent's captured stdout).
    Each verdict line must be ``N<TAB>(ok|enrich|trash)`` where N is a
    1-based sequential number matching the order in the prompt.

    Non-matching lines (narration, markdown fences, thinking) are silently
    skipped.  Also handles a ``BEGIN_VERDICTS`` / ``END_VERDICTS`` block.

    Raises ``RecapPipelineError`` if fewer than 80 % of verdicts are
    recognised (agent produced garbage output).  Missing IDs between
    80 % and 100 % default to ``"ok"`` with a warning.

    Returns ``(kept_ids, enrich_ids)``.
    """
    if not stdout_path.exists():
        logger.warning("Verdicts file not found: %s — defaulting all to ok", stdout_path)
        return [e.source_id for e in entries], []

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
    if recognition_rate < _CLASSIFY_MIN_RECOGNITION_RATE:
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
        if verdict == "trash":
            continue
        kept.append(e.source_id)
        if verdict == "enrich":
            enrich.append(e.source_id)

    return kept, enrich


def parse_enrich_result(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return {article_id: {new_title, clean_text}} from enrich output."""

    enriched = payload.get("enriched", [])
    result: dict[str, dict[str, str]] = {}
    for item in enriched:
        aid = item.get("article_id", "")
        result[aid] = {
            "new_title": item.get("new_title", ""),
            "clean_text": item.get("clean_text", ""),
        }
    return result


def parse_group_result(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return events list from group output."""

    return payload.get("events", [])


def merge_enriched_into_index(
    entries: list[ArticleIndexEntry],
    enriched: dict[str, dict[str, str]],
) -> list[ArticleIndexEntry]:
    """Update article titles from enrichment pass."""

    result: list[ArticleIndexEntry] = []
    for entry in entries:
        enriched_data = enriched.get(entry.source_id)
        if enriched_data and enriched_data.get("new_title"):
            result.append(
                ArticleIndexEntry(
                    source_id=entry.source_id,
                    title=enriched_data["new_title"],
                    url=entry.url,
                    source=entry.source,
                    published_at=entry.published_at,
                ),
            )
        else:
            result.append(entry)
    return result


def select_significant_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter events to only significant ones (high/medium significance or multi-article)."""

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


def events_to_resource_files(events: list[dict[str, Any]]) -> dict[str, bytes | str]:
    """Serialize events as individual JSON files for LLM input."""

    resources: dict[str, bytes | str] = {}
    for event in events:
        eid = event.get("event_id", str(uuid4())[:8])
        resources[f"event_{eid}.json"] = json.dumps(event, ensure_ascii=False, indent=2)
    return resources


def build_routing_defaults(settings: Settings) -> RoutingDefaults:
    """Build RoutingDefaults from Settings for the recap pipeline."""

    return RoutingDefaults(
        default_agent=settings.orchestrator.default_agent,
        task_type_profile_map=settings.orchestrator.task_type_profile_map,
        command_templates={
            "claude": settings.orchestrator.claude_command_template,
            "codex": settings.orchestrator.codex_command_template,
            "gemini": settings.orchestrator.gemini_command_template,
        },
        models={
            "claude": {
                "fast": settings.orchestrator.claude_model_fast,
                "quality": settings.orchestrator.claude_model_quality,
            },
            "codex": {
                "fast": settings.orchestrator.codex_model_fast,
                "quality": settings.orchestrator.codex_model_quality,
            },
            "gemini": {
                "fast": settings.orchestrator.gemini_model_fast,
                "quality": settings.orchestrator.gemini_model_quality,
            },
        },
    )
