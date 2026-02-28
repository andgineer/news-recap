"""Tests for enrich inline-prompt I/O helpers and parallel integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import DigestArticle
from news_recap.recap.tasks.base import RecapPipelineError
from news_recap.recap.tasks.enrich import (
    EnrichEntry,
    _ARTICLE_SEPARATOR,
    _MAX_ARTICLE_CHARS,
    _MAX_BATCH,
    _MAX_BATCH_CHARS,
    build_enrich_prompt,
    parse_enrich_stdout,
    split_into_enrich_batches,
)


def _enrich_entry(article_id: str, title: str = "", text: str = "") -> EnrichEntry:
    return EnrichEntry(
        article_id=article_id,
        title=title or f"Title {article_id}",
        text=text or f"Body text for {article_id}.",
    )


# ---------------------------------------------------------------------------
# build_enrich_prompt
# ---------------------------------------------------------------------------


class TestBuildEnrichPrompt:
    def test_embeds_articles_inline(self):
        entries = [_enrich_entry("a1", title="First"), _enrich_entry("a2", title="Second")]
        prompt = build_enrich_prompt(entries)
        assert _ARTICLE_SEPARATOR in prompt
        assert "1\nFirst" in prompt
        assert "2\nSecond" in prompt

    def test_no_unresolved_placeholders(self):
        entries = [_enrich_entry("a1")]
        prompt = build_enrich_prompt(entries)
        assert "{" not in prompt

    def test_contains_expected_count(self):
        entries = [_enrich_entry(str(i)) for i in range(5)]
        prompt = build_enrich_prompt(entries)
        assert "EXACTLY 5" in prompt

    def test_truncates_long_text(self):
        long_text = "x" * (_MAX_ARTICLE_CHARS + 5000)
        entries = [_enrich_entry("a1", text=long_text)]
        prompt = build_enrich_prompt(entries)
        assert "x" * _MAX_ARTICLE_CHARS in prompt
        assert "x" * (_MAX_ARTICLE_CHARS + 1) not in prompt

    def test_article_body_included(self):
        entries = [_enrich_entry("a1", title="Headline", text="Full article body here")]
        prompt = build_enrich_prompt(entries)
        assert "Full article body here" in prompt


# ---------------------------------------------------------------------------
# split_into_enrich_batches
# ---------------------------------------------------------------------------


class TestSplitIntoEnrichBatches:
    def test_empty_returns_empty(self):
        assert split_into_enrich_batches([]) == []

    def test_small_list_one_batch(self):
        entries = [_enrich_entry(str(i)) for i in range(8)]
        batches = split_into_enrich_batches(entries)
        assert len(batches) == 1
        assert len(batches[0]) == 8

    def test_respects_max_batch(self):
        entries = [_enrich_entry(str(i)) for i in range(_MAX_BATCH + 5)]
        batches = split_into_enrich_batches(entries)
        assert all(len(b) <= _MAX_BATCH for b in batches)
        assert sum(len(b) for b in batches) == _MAX_BATCH + 5

    def test_respects_char_budget(self):
        big_text = "x" * 10_000
        entries = [_enrich_entry(str(i), text=big_text) for i in range(20)]
        batches = split_into_enrich_batches(entries)
        assert len(batches) > 1
        for batch in batches:
            total = sum(min(len(e.text), _MAX_ARTICLE_CHARS) + len(e.title) + 10 for e in batch)
            assert total <= _MAX_BATCH_CHARS + _MAX_ARTICLE_CHARS

    def test_all_entries_preserved(self):
        entries = [_enrich_entry(str(i)) for i in range(50)]
        batches = split_into_enrich_batches(entries)
        all_ids = [e.article_id for batch in batches for e in batch]
        assert sorted(all_ids) == sorted(str(i) for i in range(50))


# ---------------------------------------------------------------------------
# parse_enrich_stdout
# ---------------------------------------------------------------------------


def _write_stdout(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "agent_stdout.log"
    p.write_text(content, "utf-8")
    return p


class TestParseEnrichStdout:
    def test_basic_parse(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        path = _write_stdout(tmp_path, "1\nNew Title One\n\n2\nNew Title Two\n\n")
        result = parse_enrich_stdout(path, entries)
        assert result == {"a1": "New Title One", "a2": "New Title Two"}

    def test_missing_file_raises(self, tmp_path):
        entries = [_enrich_entry("a1")]
        with pytest.raises(RecapPipelineError, match="stdout not found"):
            parse_enrich_stdout(tmp_path / "nonexistent.log", entries)

    def test_out_of_range_skipped(self, tmp_path):
        entries = [_enrich_entry("a1")]
        path = _write_stdout(tmp_path, "1\nGood Title\n\n99\nBad Title\n\n")
        result = parse_enrich_stdout(path, entries)
        assert result == {"a1": "Good Title"}

    def test_duplicate_ids_last_wins(self, tmp_path):
        entries = [_enrich_entry("a1")]
        path = _write_stdout(tmp_path, "1\nFirst Version\n\n1\nSecond Version\n\n")
        result = parse_enrich_stdout(path, entries)
        assert result == {"a1": "Second Version"}

    def test_empty_headline_skipped(self, tmp_path):
        entries = [_enrich_entry("a1"), _enrich_entry("a2")]
        path = _write_stdout(tmp_path, "1\n  \n\n2\nGood Title\n\n")
        result = parse_enrich_stdout(path, entries)
        assert "a1" not in result
        assert result["a2"] == "Good Title"

    def test_recognition_below_50_raises(self, tmp_path):
        entries = [_enrich_entry(f"a{i}") for i in range(10)]
        path = _write_stdout(tmp_path, "1\nOnly One\n\n")
        with pytest.raises(RecapPipelineError, match="enriched only"):
            parse_enrich_stdout(path, entries)

    def test_partial_output_accepted_above_threshold(self, tmp_path):
        entries = [_enrich_entry(f"a{i}") for i in range(4)]
        stdout = "1\nT1\n\n2\nT2\n\n3\nT3\n\n"
        path = _write_stdout(tmp_path, stdout)
        result = parse_enrich_stdout(path, entries)
        assert len(result) == 3
        assert "a3" not in result

    def test_multiline_headline_joined(self, tmp_path):
        entries = [_enrich_entry("a1")]
        path = _write_stdout(tmp_path, "1\nFirst part\nSecond part\n\n")
        result = parse_enrich_stdout(path, entries)
        assert result["a1"] == "First part Second part"

    def test_non_numeric_lines_ignored(self, tmp_path):
        entries = [_enrich_entry("a1")]
        path = _write_stdout(tmp_path, "Here is my analysis:\n\n1\nGood Title\n\n")
        result = parse_enrich_stdout(path, entries)
        assert result == {"a1": "Good Title"}


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
    inp.effective_max_parallel.return_value = 5

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
        prompts_by_task: dict[str, str] = {}

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            tid = f"enrich-{batch}"
            prompts_by_task[tid] = prompt
            return tid

        def fake_agent_side_effect(*, pipeline_dir, step_name, task_id):
            nonlocal batch_call_count
            batch_call_count += 1
            workdir = ctx.pdir / task_id
            stdout_dir = workdir / "output"
            stdout_dir.mkdir(parents=True, exist_ok=True)
            import re

            prompt_text = prompts_by_task.get(task_id, "")
            nums = re.findall(r"===ARTICLE===\n(\d+)\n(.+)", prompt_text)
            lines = [f"{num}\nNew: {title}\n" for num, title in nums]
            (stdout_dir / "agent_stdout.log").write_text("\n".join(lines), "utf-8")
            return task_id

        mock_agent = MagicMock(side_effect=fake_agent_side_effect)

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
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
        assert all(enriched[sid].startswith("New:") for sid in article_ids)

    def test_partial_failure_triggers_retry(self, tmp_path, monkeypatch):
        """First round produces partial results; unprocessed articles retried in round 2."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import enrich as enrich_mod
        from news_recap.recap.tasks import parallel as parallel_mod

        ctx = _make_fake_ctx(tmp_path)
        article_ids = [f"art{i}" for i in range(5)]
        entries = self._make_enrich_entries(article_ids)

        call_count = 0
        prompts_by_task: dict[str, str] = {}

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            tid = f"enrich-{batch}"
            prompts_by_task[tid] = prompt
            return tid

        def fake_agent_side_effect(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            workdir = ctx.pdir / task_id
            stdout_dir = workdir / "output"
            stdout_dir.mkdir(parents=True, exist_ok=True)
            import re

            prompt_text = prompts_by_task.get(task_id, "")
            nums = re.findall(r"===ARTICLE===\n(\d+)\n(.+)", prompt_text)
            lines = []
            for i, (num, title) in enumerate(nums):
                if call_count == 1 and i >= 3:
                    continue
                lines.append(f"{num}\nEnriched {title}\n")
            (stdout_dir / "agent_stdout.log").write_text("\n".join(lines), "utf-8")
            return task_id

        mock_agent = MagicMock(side_effect=fake_agent_side_effect)

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
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

    def test_empty_stdout_is_worker_crash(self, tmp_path, monkeypatch):
        """Agent produces empty stdout — recognition error triggers had_crash."""
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
            stdout_dir = workdir / "output"
            stdout_dir.mkdir(parents=True, exist_ok=True)
            (stdout_dir / "agent_stdout.log").write_text("", "utf-8")
            return task_id

        mock_agent = MagicMock(side_effect=fake_agent_no_output)

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
        ):
            result = enrich_mod._run_enrich(
                ctx,
                step_name="recap_enrich",
                entries=entries,
            )

        enriched, had_crash = result
        assert len(enriched) == 0
        assert had_crash is True
        assert call_count == 1


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

        ctx = _make_fake_ctx(tmp_path)
        big_text = "word " * 800
        entries = [
            EnrichEntry(article_id=f"art{i}", title=f"Title art{i}", text=big_text)
            for i in range(20)
        ]

        call_count = 0
        prompts_by_task: dict[str, str] = {}

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            tid = f"enrich-{batch}"
            prompts_by_task[tid] = prompt
            return tid

        def fake_agent(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RecapPipelineError("recap_enrich", "agent crashed")
            workdir = ctx.pdir / task_id
            stdout_dir = workdir / "output"
            stdout_dir.mkdir(parents=True, exist_ok=True)
            import re

            prompt_text = prompts_by_task.get(task_id, "")
            nums = re.findall(r"===ARTICLE===\n(\d+)\n(.+)", prompt_text)
            lines = [f"{num}\nNew: {title}\n" for num, title in nums]
            (stdout_dir / "agent_stdout.log").write_text("\n".join(lines), "utf-8")
            return task_id

        mock_agent = MagicMock(side_effect=fake_agent)

        with (
            patch.object(enrich_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
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
        from unittest.mock import patch

        from news_recap.recap.tasks import enrich as enrich_mod
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
            return {entries[0].article_id: f"New {entries[0].title}"}, True

        with (
            patch.object(enrich_mod, "load_cached_resource_texts", return_value=cached),
            patch.object(enrich_mod, "_run_enrich", side_effect=fake_run_enrich),
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

        with patch.object(enrich_mod, "load_cached_resource_texts", return_value={}):
            from news_recap.recap.tasks.enrich import Enrich

            e = Enrich(ctx)
            e.execute()

        assert e.fully_completed is False

    def test_partial_cache_marks_incomplete(self, tmp_path):
        """Cache returns fewer entries than remaining_ids — must stay incomplete."""
        from unittest.mock import patch

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
            return {e.article_id: f"New {e.title}" for e in entries}, False

        with (
            patch.object(enrich_mod, "load_cached_resource_texts", return_value=cached),
            patch.object(enrich_mod, "_run_enrich", side_effect=fake_run_enrich),
        ):
            from news_recap.recap.tasks.enrich import Enrich

            e = Enrich(ctx)
            e.execute()

        assert e.fully_completed is False
        assert ctx.digest.articles[0].enriched_title == "New T0"
        assert ctx.digest.articles[1].enriched_title is None
