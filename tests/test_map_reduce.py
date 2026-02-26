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
    build_block_index,
    parse_reduce_output,
    write_block_files,
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
        prompt = build_map_prompt(entries, "Russia", 10)
        assert "Breaking news" in prompt
        assert "1: Breaking news" in prompt

    def test_contains_follow_policy(self):
        entries = [_make_index_entry("a1")]
        prompt = build_map_prompt(entries, "Russia, Serbia", 10)
        assert "Russia, Serbia" in prompt

    def test_contains_max_blocks(self):
        entries = [_make_index_entry("a1")]
        prompt = build_map_prompt(entries, "none", 42)
        assert "42" in prompt

    def test_contains_stdout_instruction(self):
        entries = [_make_index_entry("a1")]
        prompt = build_map_prompt(entries, "none", 10)
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


class TestParseReduceOutput:
    def test_basic_parse(self, tmp_path):
        output_dir = tmp_path / "output" / "blocks"
        output_dir.mkdir(parents=True)
        (output_dir / "block1.txt").write_text("Snow in Serbia\na1: Snow story\na2: Road blocked\n")
        (output_dir / "block2.txt").write_text("Tech updates\na3: AI launch\n")
        blocks = parse_reduce_output(output_dir)
        assert len(blocks) == 2
        assert blocks[0].title == "Snow in Serbia"
        assert blocks[0].article_ids == ["a1", "a2"]
        assert blocks[1].article_ids == ["a3"]

    def test_missing_dir_returns_empty(self, tmp_path):
        blocks = parse_reduce_output(tmp_path / "nonexistent")
        assert blocks == []

    def test_skips_empty_files(self, tmp_path):
        output_dir = tmp_path / "output" / "blocks"
        output_dir.mkdir(parents=True)
        (output_dir / "block1.txt").write_text("Good block\na1: headline\n")
        (output_dir / "block2.txt").write_text("")
        blocks = parse_reduce_output(output_dir)
        assert len(blocks) == 1

    def test_skips_non_txt_files(self, tmp_path):
        output_dir = tmp_path / "output" / "blocks"
        output_dir.mkdir(parents=True)
        (output_dir / "block1.txt").write_text("Block\na1: headline\n")
        (output_dir / "readme.md").write_text("ignore")
        blocks = parse_reduce_output(output_dir)
        assert len(blocks) == 1


class TestWriteBlockFiles:
    """Verify block files land in input/blocks/ (not input/resources/)."""

    def test_files_written_to_input_blocks(self, tmp_path):
        blocks = [
            {"title": "Block A", "article_ids": ["a1", "a2"], "worker": 0},
            {"title": "Block B", "article_ids": ["a3"], "worker": 1},
        ]
        article_map = {"a1": "Headline 1", "a2": "Headline 2", "a3": "Headline 3"}
        write_block_files(tmp_path, blocks, article_map)

        input_blocks = tmp_path / "input" / "blocks"
        assert input_blocks.is_dir()
        assert (input_blocks / "w0_b0.txt").exists()
        assert (input_blocks / "w1_b1.txt").exists()

        content = (input_blocks / "w0_b0.txt").read_text("utf-8")
        assert content.startswith("Block A\n")
        assert "a1: Headline 1" in content
        assert "a2: Headline 2" in content

    def test_output_blocks_dir_created(self, tmp_path):
        blocks = [{"title": "B", "article_ids": ["x"], "worker": 0}]
        write_block_files(tmp_path, blocks, {"x": "H"})
        assert (tmp_path / "output" / "blocks").is_dir()

    def test_round_trip_with_parser(self, tmp_path):
        """Written block files can be parsed back by parse_reduce_output."""
        blocks = [
            {"title": "Snow in Serbia", "article_ids": ["a1", "a2"], "worker": 0},
        ]
        article_map = {"a1": "Snow story", "a2": "Road blocked"}
        write_block_files(tmp_path, blocks, article_map)

        parsed = parse_reduce_output(tmp_path / "input" / "blocks")
        assert len(parsed) == 1
        assert parsed[0].title == "Snow in Serbia"
        assert parsed[0].article_ids == ["a1", "a2"]


class TestBuildBlockIndex:
    def test_index_matches_filenames(self):
        blocks = [
            {"title": "Block A", "article_ids": ["a1"], "worker": 0},
            {"title": "Block B", "article_ids": ["a2"], "worker": 1},
        ]
        index = build_block_index(blocks)
        assert "w0_b0.txt: Block A" in index
        assert "w1_b1.txt: Block B" in index
