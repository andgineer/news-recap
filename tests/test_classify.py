"""Tests for batch classify helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.models import DigestArticle, UserPreferences
from news_recap.recap.tasks.base import RecapPipelineError
from news_recap.recap.tasks.classify import (
    _MAX_BATCH as _CLASSIFY_MAX_BATCH,
)
from news_recap.recap.tasks.classify import (
    _MAX_PARALLEL as _CLASSIFY_MAX_PARALLEL,
)
from news_recap.recap.tasks.classify import (
    _MIN_BATCH as _CLASSIFY_MIN_BATCH,
)
from news_recap.recap.tasks.classify import (
    build_classify_batch_prompt,
    parse_classify_batch_stdout,
    split_into_classify_batches,
)


def _make_entry(article_id: str) -> DigestArticle:
    return DigestArticle(
        article_id=article_id,
        title=f"Title {article_id}",
        url=f"http://example.com/{article_id}",
        source="test",
        published_at="2026-02-17T00:00:00+00:00",
        clean_text="",
    )


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

    def test_maximizes_parallelism(self):
        n = _CLASSIFY_MIN_BATCH * _CLASSIFY_MAX_PARALLEL
        entries = [_make_entry(str(i)) for i in range(n)]
        batches = split_into_classify_batches(entries, _make_prefs())
        assert len(batches) == _CLASSIFY_MAX_PARALLEL
        assert all(len(b) <= _CLASSIFY_MAX_BATCH for b in batches)
        assert sum(len(b) for b in batches) == n

    def test_even_distribution(self):
        n = 200
        entries = [_make_entry(str(i)) for i in range(n)]
        batches = split_into_classify_batches(entries, _make_prefs())
        sizes = [len(b) for b in batches]
        assert max(sizes) - min(sizes) <= 1

    def test_respects_max_batch(self):
        n = _CLASSIFY_MAX_BATCH * 3
        entries = [_make_entry(str(i)) for i in range(n)]
        batches = split_into_classify_batches(entries, _make_prefs())
        assert all(len(b) <= _CLASSIFY_MAX_BATCH for b in batches)
        assert sum(len(b) for b in batches) == n

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
        prefs = _make_prefs(exclude="sports", follow="politics")
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
            "1: ok\n2: exclude\n3: vague\n4: follow\n",
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
            "BEGIN_VERDICTS\n1\tok\n2\texclude\n3\tvague\nEND_VERDICTS",
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
            "BEGIN_VERDICTS\n1 ok\n2 exclude\nEND_VERDICTS",
        )
        kept, enrich = parse_classify_batch_stdout(stdout, entries)
        assert "a1" in kept
        assert "a2" not in kept

    def test_low_recognition_rate_raises(self, tmp_path):
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
