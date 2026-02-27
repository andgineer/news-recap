"""Tests for MAP / REDUCE pipeline helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.tasks.base import RecapPipelineError
from news_recap.recap.tasks.map_blocks import (
    build_map_prompt,
    merge_enriched_into_index,
    parse_map_stdout,
    split_into_map_chunks,
)
from news_recap.recap.tasks.reduce_blocks import (
    ReduceAction,
    ReduceBlocks,
    SplitTask,
    _blocks_to_dicts,
    _chunk_blocks,
    _interleave_by_worker,
    _load_split_tasks,
    _save_split_tasks,
    _split_intermediate,
    apply_reduce_plan,
    build_reduce_prompt,
    parse_reduce_stdout,
)


def _make_index_entry(source_id: str, title: str = "") -> ArticleIndexEntry:
    return ArticleIndexEntry(
        source_id=source_id,
        title=title or f"Title {source_id}",
        url=f"http://example.com/{source_id}",
        source="test",
        published_at="2026-01-01",
    )


class TestMergeEnrichedIntoIndex:
    def test_merge_updates_title(self):
        entries = [
            ArticleIndexEntry(source_id="a1", title="Old", url="http://ex.com", source="src"),
        ]
        enriched = {"a1": "New"}
        result = merge_enriched_into_index(entries, enriched)
        assert result[0].title == "New"

    def test_merge_keeps_original_if_no_enrichment(self):
        entries = [
            ArticleIndexEntry(source_id="a1", title="Original", url="http://ex.com", source="src"),
        ]
        result = merge_enriched_into_index(entries, {})
        assert result[0].title == "Original"


class TestSplitIntoMapChunks:
    def test_empty_returns_empty(self):
        assert split_into_map_chunks([]) == []

    def test_small_list_one_chunk(self):
        entries = [_make_index_entry(str(i)) for i in range(10)]
        chunks = split_into_map_chunks(entries)
        assert len(chunks) == 1
        assert len(chunks[0]) == 10

    def test_large_list_splits(self):
        entries = [_make_index_entry(str(i)) for i in range(900)]
        chunks = split_into_map_chunks(entries)
        assert len(chunks) == 3
        assert sum(len(c) for c in chunks) == 900

    def test_preserves_all_entries(self):
        entries = [_make_index_entry(str(i)) for i in range(500)]
        chunks = split_into_map_chunks(entries)
        all_ids = [e.source_id for c in chunks for e in c]
        assert sorted(all_ids) == sorted(str(i) for i in range(500))


class TestBuildMapPrompt:
    def test_contains_headlines(self):
        entries = [_make_index_entry("a1", "Breaking news")]
        prompt = build_map_prompt(entries, "Russia")
        assert "Breaking news" in prompt
        assert "1: Breaking news" in prompt

    def test_contains_follow_policy(self):
        entries = [_make_index_entry("a1")]
        prompt = build_map_prompt(entries, "Russia, Serbia")
        assert "Russia, Serbia" in prompt

    def test_contains_headline_count(self):
        entries = [_make_index_entry(f"a{i}") for i in range(42)]
        prompt = build_map_prompt(entries, "none")
        assert "42 total" in prompt

    def test_contains_stdout_instruction(self):
        entries = [_make_index_entry("a1")]
        prompt = build_map_prompt(entries, "none")
        assert "stdout" in prompt
        assert "BLOCK:" in prompt


class TestParseMapStdout:
    def _write_stdout(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "agent_stdout.log"
        p.write_text(content, "utf-8")
        return p

    def test_basic_parse(self, tmp_path):
        entries = [_make_index_entry(f"a{i}") for i in range(5)]
        stdout = self._write_stdout(
            tmp_path,
            "BLOCK: Snow hits Serbia\n1, 2, 3\n\nBLOCK: Tech news\n4, 5\n",
        )
        blocks = parse_map_stdout(stdout, entries, worker=1)
        assert len(blocks) == 2
        assert blocks[0]["title"] == "Snow hits Serbia"
        assert blocks[0]["article_ids"] == ["a0", "a1", "a2"]
        assert blocks[1]["article_ids"] == ["a3", "a4"]

    def test_unassigned_go_to_uncategorized(self, tmp_path):
        entries = [_make_index_entry(f"a{i}") for i in range(5)]
        stdout = self._write_stdout(
            tmp_path,
            "BLOCK: Partial block\n1, 2, 3, 4\n",
        )
        blocks = parse_map_stdout(stdout, entries, worker=1)
        assert any(b["title"] == "Uncategorized" for b in blocks)
        uncat = [b for b in blocks if b["title"] == "Uncategorized"][0]
        assert "a4" in uncat["article_ids"]

    def test_low_coverage_raises(self, tmp_path):
        entries = [_make_index_entry(f"a{i}") for i in range(10)]
        stdout = self._write_stdout(
            tmp_path,
            "BLOCK: Tiny\n1, 2\n",
        )
        with pytest.raises(RecapPipelineError, match="coverage"):
            parse_map_stdout(stdout, entries, worker=1)

    def test_missing_file_raises(self, tmp_path):
        entries = [_make_index_entry("a0")]
        with pytest.raises(RecapPipelineError, match="MAP stdout not found"):
            parse_map_stdout(tmp_path / "missing.log", entries, worker=1)

    def test_ignores_invalid_numbers(self, tmp_path):
        entries = [_make_index_entry(f"a{i}") for i in range(3)]
        stdout = self._write_stdout(
            tmp_path,
            "BLOCK: Block one\n1, 2, 3, 99, abc\n",
        )
        blocks = parse_map_stdout(stdout, entries, worker=1)
        assert len(blocks) == 1
        assert len(blocks[0]["article_ids"]) == 3

    def test_duplicate_numbers_logged(self, tmp_path):
        entries = [_make_index_entry(f"a{i}") for i in range(3)]
        stdout = self._write_stdout(
            tmp_path,
            "BLOCK: Block A\n1, 2\n\nBLOCK: Block B\n2, 3\n",
        )
        blocks = parse_map_stdout(stdout, entries, worker=1)
        assert len(blocks) == 2


class TestMapBlocksExecute:
    """Integration tests for MapBlocks.execute() partial-persist and resume."""

    def _make_ctx(self, tmp_path, entries):
        from unittest.mock import MagicMock

        from news_recap.recap.models import Digest
        from news_recap.recap.storage.pipeline_io import PipelineInput
        from news_recap.recap.tasks.base import FlowContext

        pdir = tmp_path / "pipeline"
        pdir.mkdir()

        inp = MagicMock(spec=PipelineInput)
        inp.preferences = MagicMock()
        inp.preferences.follow = "none"
        inp.effective_max_parallel.return_value = 5

        digest = Digest(
            digest_id="test",
            business_date="2026-01-01",
            status="running",
            pipeline_dir=str(pdir),
            articles=[],
        )

        ctx = FlowContext(
            pdir=pdir,
            workdir_mgr=MagicMock(),
            inp=inp,
            article_map={e.source_id: e for e in entries},
            digest=digest,
        )
        ctx.state["kept_entries"] = entries
        ctx.state["enriched_articles"] = {}
        return ctx

    def test_resume_from_partial_blocks(self, tmp_path):
        """Pre-populated digest.blocks -> only uncovered headlines sent to workers."""
        from unittest.mock import MagicMock, patch

        from news_recap.recap.models import DigestBlock
        from news_recap.recap.tasks import map_blocks as map_mod
        from news_recap.recap.tasks import parallel as parallel_mod
        from news_recap.recap.tasks.map_blocks import MapBlocks

        entries = [_make_index_entry(f"a{i}") for i in range(6)]
        ctx = self._make_ctx(tmp_path, entries)

        ctx.digest.blocks = [
            DigestBlock(title="Existing", article_ids=["a0", "a1", "a2"]),
        ]

        submitted_chunks: list[list[ArticleIndexEntry]] = []

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"map-{batch}"

        def fake_agent(*, pipeline_dir, step_name, task_id):
            workdir = ctx.pdir / task_id / "output"
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "agent_stdout.log").write_text(
                "BLOCK: New block\n1, 2, 3\n",
                "utf-8",
            )
            return task_id

        orig_split = map_mod.split_into_map_chunks

        def tracking_split(e):
            submitted_chunks.extend(orig_split(e))
            return orig_split(e)

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent(**kw))
        )

        with (
            patch.object(map_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(map_mod, "split_into_map_chunks", side_effect=tracking_split),
            patch.object(map_mod, "get_run_logger", return_value=MagicMock()),
        ):
            inst = MapBlocks(ctx)
            inst.execute()

        worker_ids = {e.source_id for chunk in submitted_chunks for e in chunk}
        assert "a0" not in worker_ids
        assert "a1" not in worker_ids
        assert "a2" not in worker_ids
        assert len(ctx.digest.blocks) > 1

    def test_failed_worker_persists_and_raises(self, tmp_path):
        """One worker fails -> partial blocks saved to digest, RecapPipelineError raised."""
        from unittest.mock import MagicMock, patch

        import pytest

        from news_recap.recap.tasks import map_blocks as map_mod
        from news_recap.recap.tasks import parallel as parallel_mod
        from news_recap.recap.tasks.base import RecapPipelineError
        from news_recap.recap.tasks.map_blocks import MapBlocks

        entries = [_make_index_entry(f"a{i}") for i in range(6)]
        ctx = self._make_ctx(tmp_path, entries)

        call_count = 0

        def fake_materialize(workdir_mgr, inp, *, step_name, batch, prompt):
            return f"map-{batch}"

        def fake_agent(*, pipeline_dir, step_name, task_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RecapPipelineError("recap_map", "agent crashed")
            workdir = ctx.pdir / task_id / "output"
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "agent_stdout.log").write_text(
                "BLOCK: Good block\n1, 2, 3\n",
                "utf-8",
            )
            return task_id

        mock_agent = MagicMock()
        mock_agent.with_options.return_value.submit.side_effect = lambda **kw: MagicMock(
            result=MagicMock(side_effect=lambda: fake_agent(**kw))
        )

        with (
            patch.object(map_mod, "materialize_step", side_effect=fake_materialize),
            patch.object(parallel_mod, "run_ai_agent", mock_agent),
            patch.object(map_mod, "get_run_logger", return_value=MagicMock()),
            patch.object(
                map_mod,
                "split_into_map_chunks",
                return_value=[
                    entries[:3],
                    entries[3:],
                ],
            ),
        ):
            with pytest.raises(RecapPipelineError, match="Worker failure"):
                inst = MapBlocks(ctx)
                inst.execute()

        assert inst.fully_completed is False
        assert len(ctx.digest.blocks) >= 1
        saved_ids = {aid for b in ctx.digest.blocks for aid in b.article_ids}
        assert len(saved_ids) > 0


class TestBuildReducePrompt:
    def test_contains_numbered_titles(self):
        blocks = [
            {"title": "Snow in Serbia", "article_ids": ["a1", "a2"]},
            {"title": "Tech news", "article_ids": ["a3"]},
        ]
        prompt = build_reduce_prompt(blocks)
        assert "1: Snow in Serbia (2 articles)" in prompt
        assert "2: Tech news (1 articles)" in prompt

    def test_contains_prompt_template(self):
        blocks = [{"title": "Block A", "article_ids": ["a1"]}]
        prompt = build_reduce_prompt(blocks)
        assert "BLOCK TITLES" in prompt
        assert "BLOCK:" in prompt
        assert "SPLIT:" in prompt


class TestParseReduceStdout:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "agent_stdout.log"
        p.write_text(content, "utf-8")
        return p

    def test_basic_block_parse(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: Serbia FM hospitalized\n1\n\nBLOCK: Tech news\n2, 3\n",
        )
        actions = parse_reduce_stdout(stdout, 3)
        assert len(actions) == 2
        assert actions[0].kind == "block"
        assert actions[0].title == "Serbia FM hospitalized"
        assert actions[0].source_indices == [1]
        assert actions[1].source_indices == [2, 3]

    def test_split_action_parsed(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "SPLIT: Mixed Iran/US block\n1, 2\n\nBLOCK: Other\n3\n",
        )
        actions = parse_reduce_stdout(stdout, 3)
        splits = [a for a in actions if a.kind == "split"]
        assert len(splits) == 1
        assert splits[0].title == "Mixed Iran/US block"
        assert splits[0].source_indices == [1, 2]

    def test_omitted_blocks_treated_as_implicit(self, tmp_path):
        stdout = self._write(tmp_path, "BLOCK: Only first\n1\n")
        actions = parse_reduce_stdout(stdout, 3)
        assert len(actions) == 3
        implicit = [a for a in actions if a.source_indices == [2] or a.source_indices == [3]]
        assert len(implicit) == 2
        for a in implicit:
            assert a.kind == "block"
            assert a.title == ""

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RecapPipelineError, match="REDUCE stdout not found"):
            parse_reduce_stdout(tmp_path / "missing.log", 3)

    def test_empty_file_raises(self, tmp_path):
        stdout = self._write(tmp_path, "")
        with pytest.raises(RecapPipelineError, match="empty"):
            parse_reduce_stdout(stdout, 3)

    def test_duplicate_source_blocks_ignored(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: First\n1, 2\n\nBLOCK: Second\n2, 3\n",
        )
        actions = parse_reduce_stdout(stdout, 3)
        assert len(actions) == 2
        assert actions[0].source_indices == [1, 2]
        assert actions[1].source_indices == [3]

    def test_all_duplicates_skipped_block_dropped(self, tmp_path):
        stdout = self._write(
            tmp_path,
            "BLOCK: First\n1, 2, 3\n\nBLOCK: Duplicate\n1, 2\n",
        )
        actions = parse_reduce_stdout(stdout, 3)
        assert len(actions) == 1
        assert actions[0].source_indices == [1, 2, 3]

    def test_no_valid_lines_raises(self, tmp_path):
        stdout = self._write(tmp_path, "Some random agent chatter\nNo blocks here\n")
        with pytest.raises(RecapPipelineError, match="no valid BLOCK/SPLIT"):
            parse_reduce_stdout(stdout, 3)


class TestSplitTasksPersistence:
    def test_round_trip(self, tmp_path):
        tasks = [
            SplitTask(title="Block A", article_ids=["a1", "a2"]),
            SplitTask(title="Block B", article_ids=["a3"]),
        ]
        _save_split_tasks(tmp_path, tasks)
        loaded = _load_split_tasks(tmp_path)
        assert len(loaded) == 2
        assert loaded[0].title == "Block A"
        assert loaded[0].article_ids == ["a1", "a2"]
        assert loaded[1].title == "Block B"

    def test_load_missing_returns_empty(self, tmp_path):
        assert _load_split_tasks(tmp_path) == []

    def test_empty_list_round_trip(self, tmp_path):
        _save_split_tasks(tmp_path, [])
        assert _load_split_tasks(tmp_path) == []


class TestReduceBlocksRestoreState:
    def test_restore_loads_persisted_split_tasks(self, tmp_path):
        from unittest.mock import MagicMock

        from news_recap.recap.models import Digest
        from news_recap.recap.tasks.base import FlowContext

        pdir = tmp_path / "pipeline"
        pdir.mkdir()

        tasks = [SplitTask(title="Broad", article_ids=["a1", "a2"])]
        _save_split_tasks(pdir, tasks)

        digest = Digest(
            digest_id="test",
            business_date="2026-01-01",
            status="running",
            pipeline_dir=str(pdir),
            articles=[],
        )
        ctx = FlowContext(
            pdir=pdir,
            workdir_mgr=MagicMock(),
            inp=MagicMock(),
            article_map={},
            digest=digest,
        )

        inst = ReduceBlocks(ctx)
        inst.restore_state()

        loaded = ctx.state["split_tasks"]
        assert len(loaded) == 1
        assert loaded[0].title == "Broad"
        assert loaded[0].article_ids == ["a1", "a2"]

    def test_restore_empty_when_no_file(self, tmp_path):
        from unittest.mock import MagicMock

        from news_recap.recap.models import Digest
        from news_recap.recap.tasks.base import FlowContext

        pdir = tmp_path / "pipeline"
        pdir.mkdir()

        digest = Digest(
            digest_id="test",
            business_date="2026-01-01",
            status="running",
            pipeline_dir=str(pdir),
            articles=[],
        )
        ctx = FlowContext(
            pdir=pdir,
            workdir_mgr=MagicMock(),
            inp=MagicMock(),
            article_map={},
            digest=digest,
        )

        inst = ReduceBlocks(ctx)
        inst.restore_state()

        assert ctx.state["split_tasks"] == []


class TestApplyReducePlan:
    def test_block_action_concatenates_articles(self):
        blocks = [
            {"title": "A", "article_ids": ["a1", "a2"]},
            {"title": "B", "article_ids": ["a3"]},
        ]
        actions = [ReduceAction(kind="block", title="Merged AB", source_indices=[1, 2])]
        final, splits = apply_reduce_plan(blocks, actions)
        assert len(final) == 1
        assert final[0].title == "Merged AB"
        assert final[0].article_ids == ["a1", "a2", "a3"]
        assert len(splits) == 0

    def test_split_action_produces_split_task(self):
        blocks = [
            {"title": "Mixed", "article_ids": ["a1", "a2", "a3"]},
        ]
        actions = [ReduceAction(kind="split", title="Mixed block", source_indices=[1])]
        final, splits = apply_reduce_plan(blocks, actions)
        assert len(final) == 0
        assert len(splits) == 1
        assert isinstance(splits[0], SplitTask)
        assert splits[0].article_ids == ["a1", "a2", "a3"]

    def test_mixed_plan(self):
        blocks = [
            {"title": "A", "article_ids": ["a1"]},
            {"title": "B", "article_ids": ["a2"]},
            {"title": "C", "article_ids": ["a3", "a4"]},
        ]
        actions = [
            ReduceAction(kind="block", title="Keep A", source_indices=[1]),
            ReduceAction(kind="split", title="Broad BC", source_indices=[2, 3]),
        ]
        final, splits = apply_reduce_plan(blocks, actions)
        assert len(final) == 1
        assert final[0].title == "Keep A"
        assert len(splits) == 1
        assert splits[0].article_ids == ["a2", "a3", "a4"]

    def test_deduplicates_article_ids(self):
        blocks = [
            {"title": "A", "article_ids": ["a1", "a2", "a3"]},
            {"title": "B", "article_ids": ["a2", "a3", "a4"]},
        ]
        actions = [ReduceAction(kind="block", title="Merged", source_indices=[1, 2])]
        final, _ = apply_reduce_plan(blocks, actions)
        assert final[0].article_ids == ["a1", "a2", "a3", "a4"]

    def test_implicit_block_uses_original_title(self):
        blocks = [{"title": "Original", "article_ids": ["a1"]}]
        actions = [ReduceAction(kind="block", title="", source_indices=[1])]
        final, _ = apply_reduce_plan(blocks, actions)
        assert final[0].title == "Original"


class TestInterleaveByWorker:
    def test_single_worker_unchanged(self):
        blocks = [{"title": f"B{i}", "article_ids": [], "worker": 1} for i in range(5)]
        result = _interleave_by_worker(blocks)
        assert result == blocks

    def test_no_worker_key_unchanged(self):
        blocks = [{"title": f"B{i}", "article_ids": []} for i in range(5)]
        result = _interleave_by_worker(blocks)
        assert result == blocks

    def test_round_robin_two_workers(self):
        blocks = [
            {"title": "W1-A", "article_ids": [], "worker": 1},
            {"title": "W1-B", "article_ids": [], "worker": 1},
            {"title": "W2-A", "article_ids": [], "worker": 2},
            {"title": "W2-B", "article_ids": [], "worker": 2},
        ]
        result = _interleave_by_worker(blocks)
        workers = [b["worker"] for b in result]
        assert workers == [1, 2, 1, 2]

    def test_uneven_workers(self):
        blocks = [
            {"title": "W1-A", "article_ids": [], "worker": 1},
            {"title": "W1-B", "article_ids": [], "worker": 1},
            {"title": "W1-C", "article_ids": [], "worker": 1},
            {"title": "W2-A", "article_ids": [], "worker": 2},
        ]
        result = _interleave_by_worker(blocks)
        assert len(result) == 4
        assert result[0]["worker"] == 1
        assert result[1]["worker"] == 2
        assert result[2]["worker"] == 1
        assert result[3]["worker"] == 1

    def test_preserves_all_blocks(self):
        blocks = [
            {"title": f"W{w}-{i}", "article_ids": [f"a{w}{i}"], "worker": w}
            for w in range(1, 4)
            for i in range(50)
        ]
        result = _interleave_by_worker(blocks)
        assert len(result) == 150
        assert set(b["title"] for b in result) == set(b["title"] for b in blocks)


class TestChunkBlocks:
    def test_single_chunk_when_small(self):
        blocks = [{"title": f"B{i}", "article_ids": [f"a{i}"]} for i in range(50)]
        chunks = _chunk_blocks(blocks, 200)
        assert len(chunks) == 1
        assert len(chunks[0]) == 50

    def test_splits_into_even_chunks(self):
        blocks = [{"title": f"B{i}", "article_ids": [f"a{i}"]} for i in range(400)]
        chunks = _chunk_blocks(blocks, 200)
        assert len(chunks) == 2
        assert len(chunks[0]) == 200
        assert len(chunks[1]) == 200

    def test_uneven_split(self):
        blocks = [{"title": f"B{i}", "article_ids": [f"a{i}"]} for i in range(350)]
        chunks = _chunk_blocks(blocks, 200)
        assert len(chunks) == 2
        assert len(chunks[0]) + len(chunks[1]) == 350
        assert all(len(c) <= 200 for c in chunks)

    def test_empty_input(self):
        assert _chunk_blocks([], 200) == []

    def test_preserves_all_blocks(self):
        blocks = [{"title": f"B{i}", "article_ids": [f"a{i}"]} for i in range(500)]
        chunks = _chunk_blocks(blocks, 200)
        flat = [b for c in chunks for b in c]
        assert len(flat) == 500
        assert flat == blocks


class TestBlocksToDicts:
    def test_converts_blocks_and_splits_with_kind(self):
        from news_recap.recap.models import DigestBlock

        blocks = [DigestBlock(title="Block A", article_ids=["a1", "a2"])]
        splits = [SplitTask(title="Split B", article_ids=["a3"])]
        result = _blocks_to_dicts(blocks, splits)
        assert len(result) == 2
        assert result[0] == {"title": "Block A", "article_ids": ["a1", "a2"], "kind": "block"}
        assert result[1] == {"title": "Split B", "article_ids": ["a3"], "kind": "split"}

    def test_empty(self):
        assert _blocks_to_dicts([], []) == []


class TestSplitIntermediate:
    def test_separates_blocks_and_splits(self):
        intermediate = [
            {"title": "Keep", "article_ids": ["a1"], "kind": "block"},
            {"title": "Broad", "article_ids": ["a2", "a3"], "kind": "split"},
            {"title": "Keep 2", "article_ids": ["a4"], "kind": "block"},
        ]
        blocks, splits = _split_intermediate(intermediate)
        assert len(blocks) == 2
        assert len(splits) == 1
        assert blocks[0].title == "Keep"
        assert splits[0].title == "Broad"
        assert splits[0].article_ids == ["a2", "a3"]

    def test_missing_kind_defaults_to_block(self):
        intermediate = [{"title": "No kind", "article_ids": ["a1"]}]
        blocks, splits = _split_intermediate(intermediate)
        assert len(blocks) == 1
        assert len(splits) == 0

    def test_empty(self):
        blocks, splits = _split_intermediate([])
        assert blocks == []
        assert splits == []
