"""Data-transformation helpers and shared types for the recap pipeline.

Business logic (article parsing, event building, etc.) used by
``prefect_flow.py``.  The legacy ``RecapPipelineRunner`` class that
previously lived here has been removed — all orchestration now goes
through Prefect.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from news_recap.config import Settings
from news_recap.orchestrator.contracts import ArticleIndexEntry
from news_recap.orchestrator.models import SourceCorpusEntry
from news_recap.orchestrator.routing import RoutingDefaults

logger = logging.getLogger(__name__)

MIN_ARTICLES_FOR_SIGNIFICANT_EVENT = 2

_DEFAULT_NOT_INTERESTING = "horoscopes, medical advice, sports (except Russia), Epstein files"
_DEFAULT_INTERESTING = "Russia, Serbia, war in Ukraine"


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
# Article / event helpers (reused by prefect_flow.py)
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
