"""Tests for recap pipeline runner helper functions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from news_recap.orchestrator.contracts import ArticleIndexEntry
from news_recap.orchestrator.models import SourceCorpusEntry
from news_recap.recap.runner import (
    RecapPipelineError,
    RecapPipelineRunner,
    _articles_needing_full_text,
    _build_event_payloads,
    _events_to_resource_files,
    _merge_enriched_into_index,
    _parse_classify_out_files,
    _parse_enrich_result,
    _parse_group_result,
    _safe_file_id,
    _select_significant_events,
)


def _make_entry(source_id: str) -> SourceCorpusEntry:
    return SourceCorpusEntry(
        source_id=source_id,
        article_id=source_id,
        title=f"Title {source_id}",
        url=f"http://example.com/{source_id}",
        source="test",
        published_at=datetime.now(tz=UTC),
    )


class TestParseClassifyOutFiles:
    def test_basic_verdicts(self, tmp_path: Path):
        entries = [_make_entry("a1"), _make_entry("a2"), _make_entry("a3")]
        for e, verdict in zip(entries, ["ok", "trash", "enrich"]):
            (tmp_path / f"{_safe_file_id(e.source_id)}_out.txt").write_text(verdict)
        kept, enrich = _parse_classify_out_files(tmp_path, entries)
        assert "a1" in kept
        assert "a2" not in kept
        assert "a3" in kept
        assert enrich == ["a3"]

    def test_missing_file_defaults_to_kept(self, tmp_path: Path):
        entries = [_make_entry("a1")]
        kept, enrich = _parse_classify_out_files(tmp_path, entries)
        assert kept == ["a1"]
        assert enrich == []


class TestParseEnrichResult:
    def test_basic_enrich(self):
        payload = {
            "enriched": [
                {"article_id": "a1", "new_title": "Better title", "clean_text": "Clean body"},
            ]
        }
        result = _parse_enrich_result(payload)
        assert "a1" in result
        assert result["a1"]["new_title"] == "Better title"

    def test_empty_enriched(self):
        result = _parse_enrich_result({"enriched": []})
        assert result == {}


class TestParseGroupResult:
    def test_basic_group(self):
        payload = {"events": [{"event_id": "e1", "article_ids": ["a1"]}]}
        result = _parse_group_result(payload)
        assert len(result) == 1
        assert result[0]["event_id"] == "e1"


class TestSelectSignificantEvents:
    def test_high_significance(self):
        events = [
            {"event_id": "e1", "significance": "high", "article_ids": ["a1"]},
            {"event_id": "e2", "significance": "low", "article_ids": ["a2"]},
        ]
        result = _select_significant_events(events)
        assert len(result) == 1
        assert result[0]["event_id"] == "e1"

    def test_multi_article_included(self):
        events = [
            {"event_id": "e1", "significance": "low", "article_ids": ["a1", "a2"]},
        ]
        result = _select_significant_events(events)
        assert len(result) == 1

    def test_single_low_excluded(self):
        events = [
            {"event_id": "e1", "significance": "low", "article_ids": ["a1"]},
        ]
        result = _select_significant_events(events)
        assert len(result) == 0


class TestMergeEnrichedIntoIndex:
    def test_merge_updates_title(self):
        entries = [
            ArticleIndexEntry(source_id="a1", title="Old", url="http://ex.com", source="src"),
        ]
        enriched = {"a1": {"new_title": "New", "clean_text": "..."}}
        result = _merge_enriched_into_index(entries, enriched)
        assert result[0].title == "New"

    def test_merge_keeps_original_if_no_enrichment(self):
        entries = [
            ArticleIndexEntry(source_id="a1", title="Original", url="http://ex.com", source="src"),
        ]
        result = _merge_enriched_into_index(entries, {})
        assert result[0].title == "Original"


class TestArticlesNeedingFullText:
    def test_collects_unique_articles(self):
        article_map = {
            "a1": ArticleIndexEntry(source_id="a1", title="T1", url="u1", source="s1"),
            "a2": ArticleIndexEntry(source_id="a2", title="T2", url="u2", source="s2"),
        }
        events = [
            {"event_id": "e1", "article_ids": ["a1", "a2"]},
            {"event_id": "e2", "article_ids": ["a1"]},
        ]
        result = _articles_needing_full_text(events, article_map)
        assert len(result) == 2


class TestBuildEventPayloads:
    def test_merge_enriched_texts(self):
        events = [{"event_id": "e1", "title": "Event", "article_ids": ["a1"], "significance": "high"}]
        article_map = {
            "a1": ArticleIndexEntry(source_id="a1", title="T", url="u", source="s"),
        }
        enriched = {"a1": {"new_title": "Enriched", "clean_text": "partial text"}}
        enriched_full = {"a1": {"new_title": "Full Title", "clean_text": "full text"}}
        result = _build_event_payloads(events, enriched, enriched_full, article_map)
        assert result[0]["articles"][0]["text"] == "full text"
        assert result[0]["articles"][0]["title"] == "Full Title"

    def test_fallback_to_partial_enrichment(self):
        events = [{"event_id": "e1", "title": "Event", "article_ids": ["a1"]}]
        article_map = {
            "a1": ArticleIndexEntry(source_id="a1", title="T", url="u", source="s"),
        }
        enriched = {"a1": {"new_title": "Partial", "clean_text": "partial text"}}
        result = _build_event_payloads(events, enriched, {}, article_map)
        assert result[0]["articles"][0]["text"] == "partial text"


class TestEventsToResourceFiles:
    def test_creates_json_files(self):
        events = [{"event_id": "e1", "title": "Test"}]
        result = _events_to_resource_files(events)
        assert "event_e1.json" in result
        assert '"event_id"' in result["event_e1.json"]


# -- _check_no_active_run tests -----------------------------------------------


def _create_test_db(db_path: Path) -> None:
    """Create minimal recap_pipeline_runs table for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recap_pipeline_runs ("
        " pipeline_id TEXT PRIMARY KEY,"
        " user_id TEXT NOT NULL DEFAULT 'default_user',"
        " business_date TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " current_step TEXT,"
        " error TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL"
        ")",
    )
    conn.commit()
    conn.close()


def _insert_run(db_path: Path, pipeline_id: str, status: str, updated_at: datetime) -> None:
    conn = sqlite3.connect(str(db_path))
    now_str = updated_at.isoformat()
    conn.execute(
        "INSERT INTO recap_pipeline_runs"
        " (pipeline_id, user_id, business_date, status, created_at, updated_at)"
        " VALUES (?, 'default_user', '2026-02-20', ?, ?, ?)",
        (pipeline_id, status, now_str, now_str),
    )
    conn.commit()
    conn.close()


class _FakeRepo:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path


class TestCheckNoActiveRun:
    def test_no_runs_passes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        runner = object.__new__(RecapPipelineRunner)
        runner._repository = _FakeRepo(db_path)
        runner._check_no_active_run()

    def test_completed_run_passes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        _insert_run(db_path, "p-done", "completed", datetime.now(tz=UTC))
        runner = object.__new__(RecapPipelineRunner)
        runner._repository = _FakeRepo(db_path)
        runner._check_no_active_run()

    def test_active_run_blocks(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        _insert_run(db_path, "p-active", "running", datetime.now(tz=UTC))
        runner = object.__new__(RecapPipelineRunner)
        runner._repository = _FakeRepo(db_path)
        with pytest.raises(RecapPipelineError, match="already running"):
            runner._check_no_active_run()

    def test_stale_run_auto_recovered(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        stale_time = datetime.now(tz=UTC) - timedelta(seconds=2000)
        _insert_run(db_path, "p-stale", "running", stale_time)
        runner = object.__new__(RecapPipelineRunner)
        runner._repository = _FakeRepo(db_path)
        runner._check_no_active_run()
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status, error FROM recap_pipeline_runs WHERE pipeline_id = 'p-stale'",
        ).fetchone()
        conn.close()
        assert row[0] == "failed"
        assert "Stale" in row[1]
