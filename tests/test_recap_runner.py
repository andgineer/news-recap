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
from news_recap.recap.tasks.enrich import (
    EnrichEntry,
    _MAX_ARTICLE_CHARS,
    _MAX_BATCH,
    _MAX_PARALLEL,
    _MIN_BATCH,
    articles_needing_full_text,
    build_enrich_prompt,
    build_event_payloads,
    parse_enrich_output_files,
    select_significant_events,
    split_into_enrich_batches,
    write_enrich_input_files,
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
# Enrich file-based I/O helpers
# ---------------------------------------------------------------------------


def _enrich_entry(article_id: str, title: str = "", text: str = "") -> EnrichEntry:
    return EnrichEntry(
        article_id=article_id,
        title=title or f"Title {article_id}",
        text=text or f"Body text for {article_id}.",
    )


class TestBuildEnrichPrompt:
    def test_is_static_string(self):
        prompt = build_enrich_prompt()
        assert "input/articles/" in prompt
        assert "output/articles/" in prompt
        assert "{" not in prompt

    def test_contains_instructions(self):
        prompt = build_enrich_prompt()
        assert "headline" in prompt.lower()
        assert "excerpt" in prompt.lower()


class TestWriteEnrichInputFiles:
    def test_creates_numbered_files(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        write_enrich_input_files(tmp_path, entries)
        d = tmp_path / "input" / "articles"
        assert (d / "1.txt").exists()
        assert (d / "2.txt").exists()
        assert not (d / "3.txt").exists()

    def test_file_format(self, tmp_path):
        entries = [_enrich_entry("a1", title="My Title", text="Para one.\n\nPara two.")]
        write_enrich_input_files(tmp_path, entries)
        content = (tmp_path / "input" / "articles" / "1.txt").read_text("utf-8")
        lines = content.split("\n", 2)
        assert lines[0] == "My Title"
        assert lines[1] == ""
        assert "Para one." in lines[2]
        assert "Para two." in lines[2]

    def test_truncates_long_text(self, tmp_path):
        long_text = "x" * (_MAX_ARTICLE_CHARS + 5000)
        entries = [_enrich_entry("a1", text=long_text)]
        write_enrich_input_files(tmp_path, entries)
        content = (tmp_path / "input" / "articles" / "1.txt").read_text("utf-8")
        body = content.split("\n\n", 1)[1]
        assert len(body.strip()) == _MAX_ARTICLE_CHARS


class TestSplitIntoEnrichBatches:
    def test_empty_returns_empty(self):
        assert split_into_enrich_batches([]) == []

    def test_small_list_one_batch(self):
        entries = [_enrich_entry(str(i)) for i in range(_MIN_BATCH)]
        batches = split_into_enrich_batches(entries)
        assert len(batches) == 1
        assert len(batches[0]) == _MIN_BATCH

    def test_maximizes_parallelism(self):
        n = _MAX_BATCH * 3
        entries = [_enrich_entry(str(i)) for i in range(n)]
        batches = split_into_enrich_batches(entries)
        assert len(batches) == min(_MAX_PARALLEL, n // _MIN_BATCH)
        assert all(len(b) <= _MAX_BATCH for b in batches)
        assert sum(len(b) for b in batches) == n

    def test_even_distribution(self):
        n = _MAX_BATCH * 2 + 1
        entries = [_enrich_entry(str(i)) for i in range(n)]
        batches = split_into_enrich_batches(entries)
        sizes = [len(b) for b in batches]
        assert max(sizes) - min(sizes) <= 1

    def test_respects_min_batch(self):
        entries = [_enrich_entry(str(i)) for i in range(_MIN_BATCH + 1)]
        batches = split_into_enrich_batches(entries)
        assert len(batches) == 1

    def test_all_entries_preserved(self):
        entries = [_enrich_entry(str(i)) for i in range(250)]
        batches = split_into_enrich_batches(entries)
        all_ids = [e.article_id for batch in batches for e in batch]
        assert sorted(all_ids) == sorted(str(i) for i in range(250))


def _write_output_article(tmp_path: Path, n: int, title: str, text: str) -> None:
    d = tmp_path / "output" / "articles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{n}.txt").write_text(f"{title}\n\n{text}\n", "utf-8")


class TestParseEnrichOutputFiles:
    def test_basic_parse(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        _write_output_article(tmp_path, 1, "New Title 1", "Excerpt one.")
        _write_output_article(tmp_path, 2, "New Title 2", "Excerpt two.")
        result = parse_enrich_output_files(tmp_path, entries)
        assert result["a1"]["new_title"] == "New Title 1"
        assert result["a1"]["clean_text"] == "Excerpt one."
        assert result["a2"]["new_title"] == "New Title 2"

    def test_missing_output_dir(self, tmp_path):
        entries = [_enrich_entry("a1")]
        result = parse_enrich_output_files(tmp_path, entries)
        assert result == {}

    def test_skips_non_numeric_filenames(self, tmp_path):
        entries = [_enrich_entry("a1")]
        _write_output_article(tmp_path, 1, "Good", "Text.")
        d = tmp_path / "output" / "articles"
        (d / "readme.txt").write_text("ignore me", "utf-8")
        result = parse_enrich_output_files(tmp_path, entries)
        assert len(result) == 1

    def test_skips_out_of_range(self, tmp_path):
        entries = [_enrich_entry("a1")]
        _write_output_article(tmp_path, 1, "Good", "Text.")
        _write_output_article(tmp_path, 0, "Zero", "Bad.")
        _write_output_article(tmp_path, 99, "Far", "Bad.")
        result = parse_enrich_output_files(tmp_path, entries)
        assert len(result) == 1

    def test_skips_no_blank_line(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        _write_output_article(tmp_path, 2, "Good", "Valid text.")
        d = tmp_path / "output" / "articles"
        (d / "1.txt").write_text("Title without separator and body", "utf-8")
        result = parse_enrich_output_files(tmp_path, entries)
        assert "a1" not in result
        assert "a2" in result

    def test_skips_empty_title(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        _write_output_article(tmp_path, 2, "Good", "Valid text.")
        d = tmp_path / "output" / "articles"
        (d / "1.txt").write_text("\n\nSome excerpt text.", "utf-8")
        result = parse_enrich_output_files(tmp_path, entries)
        assert "a1" not in result
        assert "a2" in result

    def test_skips_empty_excerpt(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        _write_output_article(tmp_path, 2, "Good", "Valid text.")
        d = tmp_path / "output" / "articles"
        (d / "1.txt").write_text("A Title\n\n", "utf-8")
        result = parse_enrich_output_files(tmp_path, entries)
        assert "a1" not in result
        assert "a2" in result

    def test_partial_output_accepted(self, tmp_path):
        entries = [_enrich_entry(f"a{i}") for i in range(4)]
        _write_output_article(tmp_path, 1, "T1", "Text 1.")
        _write_output_article(tmp_path, 3, "T3", "Text 3.")
        result = parse_enrich_output_files(tmp_path, entries)
        assert len(result) == 2
        assert "a0" in result
        assert "a2" in result

    def test_low_recognition_returns_partial(self, tmp_path):
        entries = [_enrich_entry(str(i)) for i in range(10)]
        _write_output_article(tmp_path, 1, "T", "Text.")
        result = parse_enrich_output_files(tmp_path, entries)
        assert len(result) == 1
        assert "0" in result

    def test_multiline_excerpt(self, tmp_path):
        entries = [_enrich_entry("a1")]
        excerpt = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        _write_output_article(tmp_path, 1, "Title", excerpt)
        result = parse_enrich_output_files(tmp_path, entries)
        assert "Paragraph one." in result["a1"]["clean_text"]
        assert "Paragraph three." in result["a1"]["clean_text"]


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


# ---------------------------------------------------------------------------
# _run_enrich parallel integration tests
# ---------------------------------------------------------------------------


def _make_fake_ctx(tmp_path):
    """Build a minimal FlowContext for _run_enrich tests."""
    from datetime import date
    from unittest.mock import MagicMock

    from news_recap.recap.models import Digest
    from news_recap.recap.storage.pipeline_io import PipelineInput
    from news_recap.recap.tasks.base import FlowContext, PipelineRunResult

    pdir = tmp_path / "pipeline"
    pdir.mkdir()

    inp = MagicMock(spec=PipelineInput)
    inp.min_resource_chars = 50

    digest = Digest(
        digest_id="test-digest",
        business_date="2026-01-01",
        status="running",
        pipeline_dir=str(pdir),
        articles=[],
    )

    result = PipelineRunResult(pipeline_id="test", business_date=date(2026, 1, 1))
    workdir_mgr = MagicMock()
    workdir_mgr.materialize.return_value = "enrich-1"

    return FlowContext(
        pdir=pdir,
        workdir_mgr=workdir_mgr,
        inp=inp,
        article_map={},
        result=result,
        digest=digest,
    )


class TestRunEnrichParallel:
    """Integration tests for ``_run_enrich`` submit/collect/retry loop."""

    def _make_enrich_entries(self, ids):
        return [
            EnrichEntry(article_id=sid, title=f"Title {sid}", text=f"Full text for {sid}.")
            for sid in ids
        ]

    def test_parallel_batches_all_succeed(self, tmp_path, monkeypatch):
        """Multiple batches submitted in parallel, all succeed."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod

        ctx = _make_fake_ctx(tmp_path)
        article_ids = [f"art{i}" for i in range(25)]
        entries = self._make_enrich_entries(article_ids)

        batch_call_count = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"enrich-{batch}"

        def fake_agent_side_effect(*, pipeline_dir, step_name, task_id):
            nonlocal batch_call_count
            batch_call_count += 1
            workdir = ctx.pdir / task_id
            input_dir = workdir / "input" / "articles"
            output_dir = workdir / "output" / "articles"
            output_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(input_dir.iterdir()):
                lines = f.read_text("utf-8").strip().split("\n", 2)
                title = lines[0]
                (output_dir / f.name).write_text(
                    f"New: {title}\n\nExcerpt for {title}.\n",
                    "utf-8",
                )
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent_side_effect(**kw))
        )

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(enrich_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        assert len(result) == 25
        assert batch_call_count >= 2
        assert all(result[sid]["new_title"].startswith("New:") for sid in article_ids)

    def test_partial_failure_triggers_retry(self, tmp_path, monkeypatch):
        """First round produces partial results; unprocessed articles retried in round 2."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod

        ctx = _make_fake_ctx(tmp_path)
        article_ids = [f"art{i}" for i in range(5)]
        entries = self._make_enrich_entries(article_ids)

        call_count = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"enrich-{batch}"

        def fake_agent_side_effect(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            workdir = ctx.pdir / task_id
            input_dir = workdir / "input" / "articles"
            output_dir = workdir / "output" / "articles"
            output_dir.mkdir(parents=True, exist_ok=True)
            files = sorted(input_dir.iterdir())
            for f in files:
                n = int(f.stem)
                if call_count == 1 and n > 3:
                    continue
                lines = f.read_text("utf-8").strip().split("\n", 2)
                (output_dir / f.name).write_text(
                    f"Enriched {lines[0]}\n\nExcerpt.\n",
                    "utf-8",
                )
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent_side_effect(**kw))
        )

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(enrich_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        assert len(result) == 5
        assert call_count == 2

    def test_no_progress_stops_retries(self, tmp_path, monkeypatch):
        """Agent produces no output files — loop stops after round 1 with warning."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod

        ctx = _make_fake_ctx(tmp_path)
        article_ids = [f"art{i}" for i in range(5)]
        entries = self._make_enrich_entries(article_ids)

        call_count = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"enrich-{batch}"

        def fake_agent_no_output(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            workdir = ctx.pdir / task_id
            (workdir / "output" / "articles").mkdir(parents=True, exist_ok=True)
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent_no_output(**kw))
        )

        mock_logger = MagicMock()
        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(enrich_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=mock_logger),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        assert len(result) == 0
        assert call_count == 1
        warnings = [str(c) for c in mock_logger.warning.call_args_list if "No progress" in str(c)]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# LoadResources tests
# ---------------------------------------------------------------------------


class TestLoadResources:
    """Tests for ``LoadResources`` task launcher."""

    def _make_digest_article(self, aid, verdict="vague", resource_loaded=False):
        return DigestArticle(
            article_id=aid,
            title=f"Title {aid}",
            url=f"https://example.com/{aid}",
            source="test",
            published_at="2026-02-17T00:00:00+00:00",
            clean_text="body",
            verdict=verdict,
            resource_loaded=resource_loaded,
        )

    def _make_ctx(self, tmp_path, articles, enrich_ids):
        from datetime import date
        from unittest.mock import MagicMock

        from news_recap.recap.models import Digest
        from news_recap.recap.storage.pipeline_io import PipelineInput
        from news_recap.recap.tasks.base import FlowContext, PipelineRunResult

        pdir = tmp_path / "pipeline"
        pdir.mkdir()

        inp = MagicMock(spec=PipelineInput)
        inp.min_resource_chars = 50
        inp.articles = articles

        digest = Digest(
            digest_id="test-digest",
            business_date="2026-01-01",
            status="running",
            pipeline_dir=str(pdir),
            articles=list(articles),
        )

        article_entries = [
            ArticleIndexEntry(
                source_id=a.article_id,
                title=a.title,
                url=a.url,
                source=a.source,
            )
            for a in articles
        ]

        result = PipelineRunResult(pipeline_id="test", business_date=date(2026, 1, 1))
        workdir_mgr = MagicMock()

        ctx = FlowContext(
            pdir=pdir,
            workdir_mgr=workdir_mgr,
            inp=inp,
            article_map={e.source_id: e for e in article_entries},
            result=result,
            digest=digest,
        )
        ctx.state["enrich_ids"] = enrich_ids
        return ctx

    def test_no_enrich_ids_skips(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [self._make_digest_article("a1", verdict="ok")]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[])

        with patch.object(lr_mod, "get_run_logger"):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.state["enrich_ids"] == []

    def test_loads_and_marks(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="follow"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2"])

        loaded = {"a1": ("Title a1", "text " * 50), "a2": ("Title a2", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[0].resource_loaded is True
        assert ctx.digest.articles[1].resource_loaded is True
        assert set(ctx.state["enrich_ids"]) == {"a1", "a2"}
        assert lr.fully_completed is True

    def test_failed_resources_reset_verdict(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="follow"),
            self._make_digest_article("a3", verdict="vague"),
            self._make_digest_article("a4", verdict="vague"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2", "a3", "a4"])

        loaded = {
            "a1": ("Title a1", "text " * 50),
            "a3": ("Title a3", "text " * 50),
            "a4": ("Title a4", "text " * 50),
        }

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[0].resource_loaded is True
        assert ctx.digest.articles[0].verdict == "vague"
        assert ctx.digest.articles[1].resource_loaded is False
        assert ctx.digest.articles[1].verdict == "ok"
        assert ctx.digest.articles[2].resource_loaded is True
        assert "a2" not in ctx.state["enrich_ids"]
        assert "a1" in ctx.state["enrich_ids"]

    def test_high_failure_rate_raises(self, tmp_path):
        import pytest
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod
        from news_recap.recap.tasks.base import RecapPipelineError

        articles = [self._make_digest_article(f"a{i}", verdict="vague") for i in range(10)]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[f"a{i}" for i in range(10)])

        loaded = {f"a{i}": (f"Title a{i}", "text " * 50) for i in range(5)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            with pytest.raises(RecapPipelineError):
                lr.execute()

    def test_already_loaded_skipped(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague", resource_loaded=True),
            self._make_digest_article("a2", verdict="vague"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2"])

        loaded = {"a2": ("Title a2", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[1].resource_loaded is True
        assert set(ctx.state["enrich_ids"]) == {"a1", "a2"}

    def test_restore_state(self, tmp_path):
        articles = [
            self._make_digest_article("a1", verdict="vague", resource_loaded=True),
            self._make_digest_article("a2", verdict="follow", resource_loaded=False),
            self._make_digest_article("a3", verdict="ok"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[])

        from news_recap.recap.tasks.load_resources import LoadResources

        lr = LoadResources(ctx)
        lr.restore_state()

        assert ctx.state["enrich_ids"] == ["a1"]

    def test_high_failure_persists_loaded_before_raise(self, tmp_path):
        """Successful loads are persisted even when failure rate exceeds threshold."""
        import pytest
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod
        from news_recap.recap.tasks.base import RecapPipelineError

        articles = [self._make_digest_article(f"a{i}", verdict="vague") for i in range(10)]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[f"a{i}" for i in range(10)])

        loaded = {f"a{i}": (f"Title a{i}", "text " * 50) for i in range(5)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            with pytest.raises(RecapPipelineError):
                lr.execute()

        for i in range(5):
            assert ctx.digest.articles[i].resource_loaded is True
        for i in range(5, 10):
            assert ctx.digest.articles[i].verdict == "ok"

    def test_no_url_resets_verdict(self, tmp_path):
        """Articles without URL get verdict reset to 'ok'."""
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="follow"),
        ]
        articles[1].url = ""
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2"])
        ctx.article_map["a2"] = ArticleIndexEntry(
            source_id="a2", title="Title a2", url="", source="test"
        )

        loaded = {"a1": ("Title a1", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[1].verdict == "ok"
        assert "a2" not in ctx.state["enrich_ids"]
        assert "a1" in ctx.state["enrich_ids"]

    def test_enrich_ids_scoped_to_original(self, tmp_path):
        """enrich_ids must not expand beyond the original set."""
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="ok", resource_loaded=True),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1"])

        loaded = {"a1": ("Title a1", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.state["enrich_ids"] == ["a1"]
        assert "a2" not in ctx.state["enrich_ids"]


# ---------------------------------------------------------------------------
# Enrich edge-case tests
# ---------------------------------------------------------------------------


class TestEnrichCacheEmpty:
    """Test that Enrich marks itself incomplete when cache returns nothing."""

    def test_no_cache_marks_incomplete(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import enrich as enrich_mod

        ctx = _make_fake_ctx(tmp_path)
        articles = [
            DigestArticle(
                article_id="a1",
                title="T",
                url="https://example.com/a1",
                source="s",
                published_at="2026-01-01T00:00:00+00:00",
                clean_text="body",
                verdict="vague",
                resource_loaded=True,
            ),
        ]
        ctx.digest.articles = list(articles)
        ctx.article_map = {
            "a1": ArticleIndexEntry(
                source_id="a1", title="T", url="https://example.com/a1", source="s"
            ),
        }
        ctx.state["enrich_ids"] = ["a1"]

        with (
            patch.object(enrich_mod, "load_cached_resource_texts", return_value={}),
            patch.object(enrich_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.enrich import Enrich

            e = Enrich(ctx)
            e.execute()

        assert e.fully_completed is False

    def test_partial_cache_marks_incomplete(self, tmp_path):
        """Cache returns fewer entries than remaining_ids — must stay incomplete."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod

        ctx = _make_fake_ctx(tmp_path)
        articles = [
            DigestArticle(
                article_id=f"a{i}",
                title=f"T{i}",
                url=f"https://example.com/a{i}",
                source="s",
                published_at="2026-01-01T00:00:00+00:00",
                clean_text="body",
                verdict="vague",
                resource_loaded=True,
            )
            for i in range(3)
        ]
        ctx.digest.articles = list(articles)
        ctx.article_map = {
            f"a{i}": ArticleIndexEntry(
                source_id=f"a{i}",
                title=f"T{i}",
                url=f"https://example.com/a{i}",
                source="s",
            )
            for i in range(3)
        }
        ctx.state["enrich_ids"] = ["a0", "a1", "a2"]

        cached = {"a0": ("T0", "text " * 50)}

        def fake_run_enrich(ctx, *, step_name, entries):
            return {
                e.article_id: {"new_title": f"New {e.title}", "clean_text": "ok"} for e in entries
            }

        with (
            patch.object(enrich_mod, "load_cached_resource_texts", return_value=cached),
            patch.object(enrich_mod, "_run_enrich", side_effect=fake_run_enrich),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            from news_recap.recap.tasks.enrich import Enrich

            e = Enrich(ctx)
            e.execute()

        assert e.fully_completed is False
        assert ctx.digest.articles[0].enriched_title == "New T0"
        assert ctx.digest.articles[1].enriched_title is None
