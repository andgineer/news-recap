"""Tests for recap pipeline helper functions.

Tests are grouped by the module the helpers now live in after the
runner.py breakup.
"""

from __future__ import annotations

from pathlib import Path

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import DigestArticle, UserPreferences
from news_recap.recap.tasks.base import RecapPipelineError, events_to_resource_files
from news_recap.recap.tasks.classify import (
    _MAX_BATCH as _CLASSIFY_MAX_BATCH,
)
from news_recap.recap.tasks.classify import (
    _MIN_BATCH as _CLASSIFY_MIN_BATCH,
)
from news_recap.recap.tasks.classify import (
    build_classify_batch_prompt,
    parse_classify_batch_stdout,
    split_into_classify_batches,
)
from news_recap.recap.tasks.enrich import (
    articles_needing_full_text,
    build_event_payloads,
    select_significant_events,
)
from news_recap.recap.tasks.group import merge_enriched_into_index, parse_group_result


def _make_entry(article_id: str) -> DigestArticle:
    return DigestArticle(
        article_id=article_id,
        title=f"Title {article_id}",
        url=f"http://example.com/{article_id}",
        source="test",
        published_at="2026-02-17T00:00:00+00:00",
        clean_text="",
    )


class TestParseGroupResult:
    def test_basic_group(self):
        payload = {"events": [{"event_id": "e1", "article_ids": ["a1"]}]}
        result = parse_group_result(payload)
        assert len(result) == 1
        assert result[0]["event_id"] == "e1"


class TestSelectSignificantEvents:
    def test_high_significance(self):
        events = [
            {"event_id": "e1", "significance": "high", "article_ids": ["a1"]},
            {"event_id": "e2", "significance": "low", "article_ids": ["a2"]},
        ]
        result = select_significant_events(events)
        assert len(result) == 1
        assert result[0]["event_id"] == "e1"

    def test_multi_article_included(self):
        events = [
            {"event_id": "e1", "significance": "low", "article_ids": ["a1", "a2"]},
        ]
        result = select_significant_events(events)
        assert len(result) == 1

    def test_single_low_excluded(self):
        events = [
            {"event_id": "e1", "significance": "low", "article_ids": ["a1"]},
        ]
        result = select_significant_events(events)
        assert len(result) == 0


class TestMergeEnrichedIntoIndex:
    def test_merge_updates_title(self):
        entries = [
            ArticleIndexEntry(source_id="a1", title="Old", url="http://ex.com", source="src"),
        ]
        enriched = {"a1": {"new_title": "New", "clean_text": "..."}}
        result = merge_enriched_into_index(entries, enriched)
        assert result[0].title == "New"

    def test_merge_keeps_original_if_no_enrichment(self):
        entries = [
            ArticleIndexEntry(source_id="a1", title="Original", url="http://ex.com", source="src"),
        ]
        result = merge_enriched_into_index(entries, {})
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
        result = articles_needing_full_text(events, article_map)
        assert len(result) == 2


class TestBuildEventPayloads:
    def test_merge_enriched_texts(self):
        events = [
            {"event_id": "e1", "title": "Event", "article_ids": ["a1"], "significance": "high"}
        ]
        article_map = {
            "a1": ArticleIndexEntry(source_id="a1", title="T", url="u", source="s"),
        }
        enriched = {"a1": {"new_title": "Enriched", "clean_text": "partial text"}}
        enriched_full = {"a1": {"new_title": "Full Title", "clean_text": "full text"}}
        result = build_event_payloads(events, enriched, enriched_full, article_map)
        assert result[0]["articles"][0]["text"] == "full text"
        assert result[0]["articles"][0]["title"] == "Full Title"

    def test_fallback_to_partial_enrichment(self):
        events = [{"event_id": "e1", "title": "Event", "article_ids": ["a1"]}]
        article_map = {
            "a1": ArticleIndexEntry(source_id="a1", title="T", url="u", source="s"),
        }
        enriched = {"a1": {"new_title": "Partial", "clean_text": "partial text"}}
        result = build_event_payloads(events, enriched, {}, article_map)
        assert result[0]["articles"][0]["text"] == "partial text"


class TestEventsToResourceFiles:
    def test_creates_json_files(self):
        events = [{"event_id": "e1", "title": "Test"}]
        result = events_to_resource_files(events)
        assert "event_e1.json" in result
        assert '"event_id"' in result["event_e1.json"]


# ---------------------------------------------------------------------------
# Batch classify helpers
# ---------------------------------------------------------------------------


def _make_prefs(**kwargs):
    return UserPreferences(**kwargs)


class TestSplitIntoClassifyBatches:
    def test_empty_returns_empty(self):
        assert split_into_classify_batches([], _make_prefs()) == []

    def test_small_list_one_batch(self):
        entries = [_make_entry(str(i)) for i in range(10)]
        batches = split_into_classify_batches(entries, _make_prefs())
        assert len(batches) == 1
        assert sum(len(b) for b in batches) == 10

    def test_splits_on_max_batch_size(self):
        n = _CLASSIFY_MAX_BATCH + _CLASSIFY_MIN_BATCH
        entries = [_make_entry(str(i)) for i in range(n)]
        batches = split_into_classify_batches(entries, _make_prefs())
        assert len(batches) >= 2
        assert all(len(b) <= _CLASSIFY_MAX_BATCH for b in batches)
        assert sum(len(b) for b in batches) == n

    def test_tiny_trailing_batch_merged(self):
        n_tail = _CLASSIFY_MIN_BATCH - 1
        entries = [_make_entry(str(i)) for i in range(_CLASSIFY_MAX_BATCH + n_tail)]
        batches = split_into_classify_batches(entries, _make_prefs())
        assert all(len(b) >= _CLASSIFY_MIN_BATCH for b in batches)
        assert sum(len(b) for b in batches) == _CLASSIFY_MAX_BATCH + n_tail

    def test_all_entries_preserved(self):
        entries = [_make_entry(str(i)) for i in range(300)]
        batches = split_into_classify_batches(entries, _make_prefs())
        all_ids = [e.article_id for batch in batches for e in batch]
        assert sorted(all_ids) == sorted(str(i) for i in range(300))


class TestBuildClassifyBatchPrompt:
    def test_contains_headlines(self):
        entries = [_make_entry("a1"), _make_entry("a2")]
        prefs = _make_prefs()
        prompt = build_classify_batch_prompt(entries, prefs)
        assert "a1" in prompt
        assert "Title a1" in prompt
        assert "a2" in prompt

    def test_contains_expected_count(self):
        entries = [_make_entry(str(i)) for i in range(7)]
        prompt = build_classify_batch_prompt(entries, _make_prefs())
        assert "7" in prompt

    def test_contains_policies(self):
        prefs = _make_prefs(trash="sports", follow="politics")
        prompt = build_classify_batch_prompt([_make_entry("x")], prefs)
        assert "sports" in prompt
        assert "politics" in prompt

    def test_contains_stdout_instruction(self):
        prompt = build_classify_batch_prompt([_make_entry("x")], _make_prefs())
        assert "stdout" in prompt


class TestParseClassifyBatchStdout:
    def _write_stdout(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "agent_stdout.log"
        p.write_text(content, "utf-8")
        return p

    def test_basic_colon_format(self, tmp_path):
        entries = [_make_entry("a1"), _make_entry("a2"), _make_entry("a3"), _make_entry("a4")]
        stdout = self._write_stdout(
            tmp_path,
            "1: ok\n2: trash\n3: vague\n4: follow\n",
        )
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert "a1" in kept
        assert "a2" not in kept
        assert "a3" in kept
        assert "a4" in kept
        assert sorted(enrich) == ["a3", "a4"]

    def test_tab_format_still_works(self, tmp_path):
        entries = [_make_entry("a1"), _make_entry("a2"), _make_entry("a3")]
        stdout = self._write_stdout(
            tmp_path,
            "BEGIN_VERDICTS\n1\tok\n2\ttrash\n3\tvague\nEND_VERDICTS",
        )
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert "a1" in kept
        assert "a2" not in kept
        assert enrich == ["a3"]

    def test_follow_counts_as_enrich(self, tmp_path):
        entries = [_make_entry("a1"), _make_entry("a2")]
        stdout = self._write_stdout(tmp_path, "1: follow\n2: ok\n")
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert kept == ["a1", "a2"]
        assert enrich == ["a1"]

    def test_missing_file_defaults_all_ok(self, tmp_path):
        entries = [_make_entry("a1"), _make_entry("a2")]
        missing = tmp_path / "nonexistent.log"
        kept, enrich = parse_classify_batch_stdout(missing, entries)
        assert kept == ["a1", "a2"]
        assert enrich == []

    def test_missing_markers_scans_full_text(self, tmp_path):
        entries = [_make_entry("a1")]
        stdout = self._write_stdout(tmp_path, "1: ok\n")
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert "a1" in kept

    def test_space_delimiter_fallback(self, tmp_path):
        entries = [_make_entry("a1"), _make_entry("a2")]
        stdout = self._write_stdout(
            tmp_path,
            "BEGIN_VERDICTS\n1 ok\n2 trash\nEND_VERDICTS",
        )
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert "a1" in kept
        assert "a2" not in kept

    def test_low_recognition_rate_raises(self, tmp_path):
        import pytest

        entries = [_make_entry(str(i)) for i in range(10)]
        stdout = self._write_stdout(tmp_path, "BEGIN_VERDICTS\n1: ok\nEND_VERDICTS")
        with pytest.raises(RecapPipelineError):
            parse_classify_batch_stdout(stdout, entries)

    def test_missing_ids_default_to_ok(self, tmp_path):
        entries = [_make_entry(f"x{i}") for i in range(5)]
        content = "\n".join(f"{i + 1}: ok" for i in range(4))
        stdout = self._write_stdout(tmp_path, f"BEGIN_VERDICTS\n{content}\nEND_VERDICTS")
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert "x4" in kept
        assert len(kept) == 5
