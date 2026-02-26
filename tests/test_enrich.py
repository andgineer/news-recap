"""Tests for enrich file-based I/O helpers and parallel integration."""

from __future__ import annotations

from pathlib import Path

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import DigestArticle
from news_recap.recap.tasks.enrich import (
    EnrichEntry,
    _MAX_ARTICLE_CHARS,
    _MAX_BATCH,
    _MAX_PARALLEL,
    _MIN_BATCH,
    build_enrich_prompt,
    parse_enrich_output_files,
    split_into_enrich_batches,
    write_enrich_input_files,
)


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
# _run_enrich parallel integration tests
# ---------------------------------------------------------------------------


def _make_fake_ctx(tmp_path):
    """Build a minimal FlowContext for _run_enrich tests."""
    from unittest.mock import MagicMock

    from news_recap.recap.models import Digest
    from news_recap.recap.storage.pipeline_io import PipelineInput
    from news_recap.recap.tasks.base import FlowContext

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

    workdir_mgr = MagicMock()
    workdir_mgr.materialize.return_value = "enrich-1"

    return FlowContext(
        pdir=pdir,
        workdir_mgr=workdir_mgr,
        inp=inp,
        article_map={},
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
        from news_recap.recap.tasks import parallel as parallel_mod

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
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        enriched, had_crash = result
        assert len(enriched) == 25
        assert had_crash is False
        assert batch_call_count >= 2
        assert all(enriched[sid]["new_title"].startswith("New:") for sid in article_ids)

    def test_partial_failure_triggers_retry(self, tmp_path, monkeypatch):
        """First round produces partial results; unprocessed articles retried in round 2."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod
        from news_recap.recap.tasks import parallel as parallel_mod

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
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        enriched, had_crash = result
        assert len(enriched) == 5
        assert had_crash is False
        assert call_count == 2

    def test_no_progress_stops_retries(self, tmp_path, monkeypatch):
        """Agent produces no output files — loop stops after round 1 with warning."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod
        from news_recap.recap.tasks import parallel as parallel_mod

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
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=mock_logger),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        enriched, had_crash = result
        assert len(enriched) == 0
        assert had_crash is False
        assert call_count == 1
        warnings = [str(c) for c in mock_logger.warning.call_args_list if "No progress" in str(c)]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Crash-flag tests
# ---------------------------------------------------------------------------


class TestEnrichCrashFlag:
    """Tests for crash-flag propagation in _run_enrich and Enrich.execute()."""

    def _make_enrich_entries(self, ids):
        return [
            EnrichEntry(article_id=sid, title=f"Title {sid}", text=f"Full text for {sid}.")
            for sid in ids
        ]

    def test_crash_flag_stops_and_returns_partial(self, tmp_path):
        """One future raises RecapPipelineError -> returns (partial, True), no further rounds."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod
        from news_recap.recap.tasks import parallel as parallel_mod
        from news_recap.recap.tasks.base import RecapPipelineError

        ctx = _make_fake_ctx(tmp_path)
        entries = self._make_enrich_entries([f"art{i}" for i in range(20)])

        call_count = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"enrich-{batch}"

        def fake_agent(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RecapPipelineError("recap_enrich", "agent crashed")
            workdir = ctx.pdir / task_id
            input_dir = workdir / "input" / "articles"
            output_dir = workdir / "output" / "articles"
            output_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(input_dir.iterdir()):
                lines = f.read_text("utf-8").strip().split("\n", 2)
                (output_dir / f.name).write_text(
                    f"New: {lines[0]}\n\nExcerpt.\n",
                    "utf-8",
                )
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent(**kw))
        )

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            enriched, had_crash = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        assert had_crash is True
        assert len(enriched) > 0
        assert len(enriched) < 20

    def test_execute_raises_on_crash(self, tmp_path):
        """Enrich.execute() persists partial enrichment and raises on crash."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.contracts import ArticleIndexEntry
        from news_recap.recap.tasks import enrich as enrich_mod
        from news_recap.recap.tasks.base import RecapPipelineError
        from news_recap.recap.tasks.enrich import Enrich

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

        cached = {f"a{i}": (f"T{i}", "text " * 50) for i in range(3)}

        def fake_run_enrich(ctx, *, step_name, entries):
            partial = {
                entries[0].article_id: {
                    "new_title": f"New {entries[0].title}",
                    "clean_text": "ok",
                },
            }
            return partial, True

        import pytest

        with (
            patch.object(enrich_mod, "load_cached_resource_texts", return_value=cached),
            patch.object(enrich_mod, "_run_enrich", side_effect=fake_run_enrich),
            patch.object(enrich_mod, "get_run_logger", return_value=MagicMock()),
        ):
            with pytest.raises(RecapPipelineError, match="crash"):
                e = Enrich(ctx)
                e.execute()

        assert e.fully_completed is False
        enriched_articles = [a for a in ctx.digest.articles if a.enriched_title]
        assert len(enriched_articles) >= 1


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
            enriched = {
                e.article_id: {"new_title": f"New {e.title}", "clean_text": "ok"} for e in entries
            }
            return enriched, False

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
