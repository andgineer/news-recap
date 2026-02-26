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

    def test_missing_file_raises(self, tmp_path):
        entries = [_make_entry("a1"), _make_entry("a2")]
        missing = tmp_path / "nonexistent.log"
        with pytest.raises(RecapPipelineError, match="Verdicts file not found"):
            parse_classify_batch_stdout(missing, entries)

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


class TestClassifyExecutePartialPersist:
    """Verify that Classify.execute() syncs partial verdicts and raises on batch failure."""

    def test_execute_partial_persist_and_raise(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from news_recap.recap.contracts import ArticleIndexEntry
        from news_recap.recap.models import Digest
        from news_recap.recap.storage.pipeline_io import PipelineInput
        from news_recap.recap.tasks import classify as classify_mod
        from news_recap.recap.tasks import parallel as parallel_mod
        from news_recap.recap.tasks.base import FlowContext
        from news_recap.recap.tasks.classify import Classify

        pdir = tmp_path / "pipeline"
        pdir.mkdir()

        articles = [_make_entry(f"a{i}") for i in range(6)]

        inp = MagicMock(spec=PipelineInput)
        inp.articles = articles
        inp.preferences = _make_prefs()
        inp.effective_max_parallel.return_value = 5

        digest = Digest(
            digest_id="test",
            business_date="2026-01-01",
            status="running",
            pipeline_dir=str(pdir),
            articles=[
                DigestArticle(
                    article_id=a.article_id,
                    title=a.title,
                    url=a.url,
                    source=a.source,
                    published_at=a.published_at,
                    clean_text="",
                )
                for a in articles
            ],
        )

        ctx = FlowContext(
            pdir=pdir,
            workdir_mgr=MagicMock(),
            inp=inp,
            article_map={
                a.article_id: ArticleIndexEntry(
                    source_id=a.article_id,
                    title=a.title,
                    url=a.url,
                    source=a.source,
                )
                for a in articles
            },
            digest=digest,
        )

        batch_num = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"classify-{batch}"

        def fake_agent_side_effect(*, pipeline_dir, step_name, task_id):
            nonlocal batch_num
            batch_num += 1
            if batch_num == 2:
                raise RecapPipelineError("recap_classify", "agent crashed")
            workdir = pdir / task_id / "output"
            workdir.mkdir(parents=True, exist_ok=True)
            content = "\n".join(f"{i + 1}: ok" for i in range(6))
            (workdir / "agent_stdout.log").write_text(content, "utf-8")
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent_side_effect(**kw))
        )

        with (
            patch.object(classify_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(classify_mod, "get_run_logger", return_value=MagicMock()),
            patch.object(
                classify_mod,
                "split_into_classify_batches",
                return_value=[
                    articles[:3],
                    articles[3:],
                ],
            ),
        ):
            with pytest.raises(RecapPipelineError, match="batch.*failed"):
                inst = Classify(ctx)
                inst.execute()

        classified = [a for a in digest.articles if a.verdict is not None]
        assert len(classified) >= 3
        unclassified = [a for a in digest.articles if a.verdict is None]
        assert len(unclassified) >= 3
