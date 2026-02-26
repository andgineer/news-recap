"""Tests for SPLIT pipeline phase (split_blocks.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.tasks.base import RecapPipelineError
from news_recap.recap.tasks.reduce_blocks import SplitTask
from news_recap.recap.tasks.split_blocks import (
    SplitBlocks,
    build_split_prompt,
    parse_split_stdout,
)


class TestBuildSplitPrompt:
    def test_sequential_numbering(self):
        task = SplitTask(title="Broad block", article_ids=["a1", "a2", "a3"])
        hmap = {"a1": "Headline A", "a2": "Headline B", "a3": "Headline C"}
        prompt = build_split_prompt(task, hmap)
        assert "1: Headline A" in prompt
        assert "2: Headline B" in prompt
        assert "3: Headline C" in prompt

    def test_contains_template_markers(self):
        task = SplitTask(title="Test", article_ids=["a1"])
        prompt = build_split_prompt(task, {"a1": "H"})
        assert "BLOCK:" in prompt
        assert "ARTICLES" in prompt

    def test_fallback_to_article_id(self):
        task = SplitTask(title="Test", article_ids=["a1"])
        prompt = build_split_prompt(task, {})
        assert "1: a1" in prompt


class TestParseSplitStdout:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "agent_stdout.log"
        p.write_text(content, "utf-8")
        return p

    def test_basic_split(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: Iran nuclear talks\n1, 2, 3\n\nBLOCK: Trump SOTU\n4, 5\n",
        )
        blocks = parse_split_stdout(stdout, ["a1", "a2", "a3", "a4", "a5"])
        assert len(blocks) == 2
        assert blocks[0].title == "Iran nuclear talks"
        assert blocks[0].article_ids == ["a1", "a2", "a3"]
        assert blocks[1].article_ids == ["a4", "a5"]

    def test_full_coverage_required(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: Partial\n1\n",
        )
        with pytest.raises(RecapPipelineError, match="coverage"):
            parse_split_stdout(stdout, ["a1", "a2", "a3", "a4", "a5"])

    def test_unassigned_appended_to_last_block(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: First\n1, 2, 3\n\nBLOCK: Second\n4\n",
        )
        blocks = parse_split_stdout(stdout, ["a1", "a2", "a3", "a4", "a5"])
        assert len(blocks) == 2
        assert "a5" in blocks[-1].article_ids

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RecapPipelineError, match="SPLIT stdout not found"):
            parse_split_stdout(tmp_path / "missing.log", ["a1"])

    def test_empty_file_raises(self, tmp_path):
        stdout = self._write(tmp_path, "")
        with pytest.raises(RecapPipelineError, match="empty"):
            parse_split_stdout(stdout, ["a1"])

    def test_ignores_invalid_numbers(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: All\n1, 2, 3, 99\n",
        )
        blocks = parse_split_stdout(stdout, ["a1", "a2", "a3"])
        assert len(blocks) == 1
        assert len(blocks[0].article_ids) == 3

    def test_single_article_blocks(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: Story A\n1\n\nBLOCK: Story B\n2\n\nBLOCK: Story C\n3\n",
        )
        blocks = parse_split_stdout(stdout, ["a1", "a2", "a3"])
        assert len(blocks) == 3
        assert blocks[0].article_ids == ["a1"]
        assert blocks[1].article_ids == ["a2"]
        assert blocks[2].article_ids == ["a3"]


def _make_entry(source_id: str, title: str = "") -> ArticleIndexEntry:
    return ArticleIndexEntry(
        source_id=source_id,
        title=title or f"Title {source_id}",
        url=f"http://example.com/{source_id}",
        source="test",
        published_at="2026-01-01",
    )


def _make_split_ctx(tmp_path, split_tasks, articles=None):
    from news_recap.recap.models import Digest, DigestBlock
    from news_recap.recap.storage.pipeline_io import PipelineInput
    from news_recap.recap.tasks.base import FlowContext

    pdir = tmp_path / "pipeline"
    pdir.mkdir()

    if articles is None:
        all_ids = {aid for t in split_tasks for aid in t.article_ids}
        articles = [_make_entry(aid) for aid in sorted(all_ids)]

    digest = Digest(
        digest_id="test",
        business_date="2026-01-01",
        status="running",
        pipeline_dir=str(pdir),
        articles=[],
    )
    digest.blocks = [DigestBlock(title="Existing", article_ids=["pre1"])]

    ctx = FlowContext(
        pdir=pdir,
        workdir_mgr=MagicMock(),
        inp=MagicMock(spec=PipelineInput),
        article_map={e.source_id: e for e in articles},
        digest=digest,
    )
    ctx.state["split_tasks"] = split_tasks
    ctx.state["enriched_articles"] = {}
    return ctx


class TestSplitBlocksExecute:
    def test_no_split_tasks_is_noop(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import split_blocks as mod

        ctx = _make_split_ctx(tmp_path, [])
        with patch.object(mod, "get_run_logger", return_value=MagicMock()):
            SplitBlocks.run(ctx)
        assert len(ctx.digest.blocks) == 1
        assert ctx.digest.blocks[0].title == "Existing"

    def test_successful_split_extends_blocks(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import parallel as parallel_mod
        from news_recap.recap.tasks import split_blocks as mod

        tasks = [SplitTask(title="Broad", article_ids=["a1", "a2", "a3"])]
        ctx = _make_split_ctx(tmp_path, tasks)

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"split-{batch}"

        def fake_agent(*, pipeline_dir, step_name, task_id):
            workdir = ctx.pdir / task_id / "output"
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "agent_stdout.log").write_text(
                "BLOCK: Iran talks\n1, 2\n\nBLOCK: US policy\n3\n",
                "utf-8",
            )
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent(**kw))
        )

        with (
            patch.object(mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(mod, "get_run_logger", return_value=MagicMock()),
            patch.object(mod, "next_batch_number", return_value=1),
        ):
            inst = SplitBlocks(ctx)
            inst.execute()

        assert len(ctx.digest.blocks) == 3
        new_titles = {b.title for b in ctx.digest.blocks}
        assert "Iran talks" in new_titles
        assert "US policy" in new_titles
        assert "Existing" in new_titles

    def test_failed_worker_partial_save_and_raises(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from news_recap.recap.tasks import parallel as parallel_mod
        from news_recap.recap.tasks import split_blocks as mod
        from news_recap.recap.tasks.base import RecapPipelineError

        tasks = [
            SplitTask(title="Good", article_ids=["a1", "a2"]),
            SplitTask(title="Bad", article_ids=["a3", "a4"]),
        ]
        ctx = _make_split_ctx(tmp_path, tasks)

        call_count = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"split-{batch}"

        def fake_agent(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RecapPipelineError("recap_split", "agent crashed")
            workdir = ctx.pdir / task_id / "output"
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "agent_stdout.log").write_text(
                "BLOCK: Split result\n1, 2\n",
                "utf-8",
            )
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent(**kw))
        )

        with (
            patch.object(mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(mod, "get_run_logger", return_value=MagicMock()),
            patch.object(mod, "next_batch_number", return_value=1),
        ):
            with pytest.raises(RecapPipelineError, match="Worker failure"):
                inst = SplitBlocks(ctx)
                inst.execute()

        assert inst.fully_completed is False
        assert len(ctx.digest.blocks) >= 2
