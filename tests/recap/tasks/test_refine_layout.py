"""Tests for refine_layout: parser, validation, gate, and fallback."""

from __future__ import annotations

from news_recap.recap.models import DigestSection
from news_recap.recap.tasks.refine_layout import (
    _build_layout_block,
    _build_prompt_mapping,
    _parse_refine_output,
    _remap_sections,
    needs_refinement,
)


# ---------------------------------------------------------------------------
# needs_refinement gate
# ---------------------------------------------------------------------------


class TestNeedsRefinement:
    def test_empty_sections(self) -> None:
        assert needs_refinement([], 10) is False

    def test_zero_blocks(self) -> None:
        s = [DigestSection(title="A", block_indices=[0])]
        assert needs_refinement(s, 0) is False

    def test_triggers_on_tiny_section(self) -> None:
        sections = [
            DigestSection(title="Big", block_indices=[0, 1, 2, 3, 4]),
            DigestSection(title="Tiny", block_indices=[5]),
        ]
        assert needs_refinement(sections, 6) is True

    def test_triggers_on_two_block_section(self) -> None:
        sections = [
            DigestSection(title="Big", block_indices=[0, 1, 2, 3, 4]),
            DigestSection(title="Small", block_indices=[5, 6]),
        ]
        assert needs_refinement(sections, 7) is True

    def test_many_sections_all_large_skips(self) -> None:
        sections = [
            DigestSection(title="A", block_indices=[0, 1, 2]),
            DigestSection(title="B", block_indices=[3, 4, 5]),
            DigestSection(title="C", block_indices=[6, 7, 8]),
            DigestSection(title="D", block_indices=[9, 10, 11]),
        ]
        # All sections have 3+ blocks — no refinement needed
        assert needs_refinement(sections, 12) is False

    def test_clean_layout_skips(self) -> None:
        sections = [
            DigestSection(title="A", block_indices=[0, 1, 2, 3, 4]),
            DigestSection(title="B", block_indices=[5, 6, 7, 8, 9]),
        ]
        # No section < 3 blocks → ok
        assert needs_refinement(sections, 10) is False

    def test_single_batch_with_one_block_section_triggers(self) -> None:
        sections = [
            DigestSection(title="A", block_indices=[0, 1, 2, 3]),
            DigestSection(title="Single", block_indices=[4]),
        ]
        assert needs_refinement(sections, 5) is True


# ---------------------------------------------------------------------------
# _build_layout_block
# ---------------------------------------------------------------------------


class TestBuildLayoutBlock:
    def test_basic_output(self) -> None:
        sections = [
            DigestSection(title="Politics", block_indices=[0, 1]),
            DigestSection(title="Tech", block_indices=[2]),
        ]
        block_titles = ["Elections", "Budget", "AI News"]
        result = _build_layout_block(sections, block_titles)
        assert "SECTION [SMALL]: Politics" in result
        assert "1. Elections" in result
        assert "2. Budget" in result
        assert "SECTION [SMALL]: Tech" in result
        assert "3. AI News" in result

    def test_small_tag_only_on_small_sections(self) -> None:
        sections = [
            DigestSection(title="Big", block_indices=[0, 1, 2, 3]),
            DigestSection(title="Tiny", block_indices=[4]),
        ]
        block_titles = ["A", "B", "C", "D", "E"]
        result = _build_layout_block(sections, block_titles)
        assert "SECTION: Big" in result
        assert "[SMALL]" not in result.split("\n")[0]
        assert "SECTION [SMALL]: Tiny" in result

    def test_numbering_is_global(self) -> None:
        sections = [
            DigestSection(title="A", block_indices=[0]),
            DigestSection(title="B", block_indices=[1]),
        ]
        block_titles = ["First", "Second"]
        result = _build_layout_block(sections, block_titles)
        lines = [ln.strip() for ln in result.splitlines() if ln.strip()]
        numbered = [ln for ln in lines if ln[0].isdigit()]
        assert numbered == ["1. First", "2. Second"]


# ---------------------------------------------------------------------------
# _parse_refine_output
# ---------------------------------------------------------------------------


class TestParseRefineOutput:
    def test_well_formed(self) -> None:
        text = (
            "SECTION: World Affairs\n"
            "SECTION_SUMMARY: Global political events.\n"
            "BLOCKS: 1, 2, 3\n"
            "\n"
            "SECTION: Technology\n"
            "SECTION_SUMMARY: Tech news.\n"
            "BLOCKS: 4, 5\n"
        )
        result = _parse_refine_output(text, 5)
        assert result is not None
        assert len(result) == 2
        assert result[0].title == "World Affairs"
        assert result[0].summary == "Global political events."
        assert result[0].block_indices == [0, 1, 2]
        assert result[1].title == "Technology"
        assert result[1].block_indices == [3, 4]

    def test_missing_block_salvaged_when_within_threshold(self) -> None:
        text = "SECTION: Only\nSECTION_SUMMARY: Partial.\nBLOCKS: 1, 2\n"
        # 3 blocks, 1 missing — within 5% threshold (max(1, 3//20)=1)
        result = _parse_refine_output(text, 3)
        assert result is not None
        assert 2 in result[0].block_indices

    def test_duplicate_block_returns_none(self) -> None:
        text = (
            "SECTION: A\n"
            "SECTION_SUMMARY: x.\n"
            "BLOCKS: 1, 2\n"
            "\n"
            "SECTION: B\n"
            "SECTION_SUMMARY: y.\n"
            "BLOCKS: 2, 3\n"
        )
        # Block 2 assigned to both sections
        assert _parse_refine_output(text, 3) is None

    def test_out_of_range_block_returns_none(self) -> None:
        text = "SECTION: A\nSECTION_SUMMARY: x.\nBLOCKS: 1, 2, 99\n"
        assert _parse_refine_output(text, 2) is None

    def test_empty_output_returns_none(self) -> None:
        assert _parse_refine_output("", 5) is None

    def test_no_blocks_line_returns_none(self) -> None:
        text = "SECTION: A\nSECTION_SUMMARY: x.\n"
        # Section without blocks → empty section, missing blocks
        assert _parse_refine_output(text, 3) is None

    def test_single_section_all_blocks(self) -> None:
        text = "SECTION: Everything\nSECTION_SUMMARY: All news.\nBLOCKS: 1, 2, 3, 4\n"
        result = _parse_refine_output(text, 4)
        assert result is not None
        assert len(result) == 1
        assert result[0].block_indices == [0, 1, 2, 3]

    def test_parser_returns_only_section_structure(self) -> None:
        """Parser output contains only section titles, summaries, and block indices."""
        text = "SECTION: Merged\nSECTION_SUMMARY: Combined.\nBLOCKS: 1, 2\n"
        result = _parse_refine_output(text, 2)
        assert result is not None
        assert len(result) == 1
        sec = result[0]
        assert sec.title == "Merged"
        assert sec.summary == "Combined."
        assert sec.block_indices == [0, 1]

    def test_case_insensitive_keywords(self) -> None:
        text = "section: Test\nsection_summary: Summary.\nblocks: 1, 2\n"
        result = _parse_refine_output(text, 2)
        assert result is not None
        assert result[0].title == "Test"

    def test_no_summary_still_parses(self) -> None:
        text = "SECTION: No Summary Section\nBLOCKS: 1, 2, 3\n"
        result = _parse_refine_output(text, 3)
        assert result is not None
        assert result[0].summary == ""
        assert result[0].block_indices == [0, 1, 2]

    def test_markdown_bold_keywords(self) -> None:
        text = (
            "**SECTION: World Affairs**\n"
            "SECTION_SUMMARY: Global events.\n"
            "BLOCKS: 1, 2\n"
            "\n"
            "**SECTION: Tech**\n"
            "SECTION_SUMMARY: Technology news.\n"
            "BLOCKS: 3, 4\n"
        )
        result = _parse_refine_output(text, 4)
        assert result is not None
        assert len(result) == 2
        assert result[0].title == "World Affairs"
        assert result[1].title == "Tech"

    def test_small_number_of_missing_blocks_salvaged(self) -> None:
        """A few omitted blocks are auto-appended to the last section."""
        assigned = list(range(1, 99))  # blocks 1..98
        text = (
            "SECTION: Main\n"
            "SECTION_SUMMARY: Most blocks.\n"
            f"BLOCKS: {', '.join(str(x) for x in assigned[:49])}\n"
            "\n"
            "SECTION: Other\n"
            "SECTION_SUMMARY: Rest.\n"
            f"BLOCKS: {', '.join(str(x) for x in assigned[49:])}\n"
        )
        # 100 total blocks but only 98 assigned (missing 99 and 100)
        # max_missing = max(1, 100//20) = 5, so 2 missing is tolerated
        result = _parse_refine_output(text, 100)
        assert result is not None
        assert len(result) == 2
        # Missing blocks 98, 99 (0-based) appended to last section
        assert 98 in result[-1].block_indices
        assert 99 in result[-1].block_indices

    def test_too_many_missing_blocks_returns_none(self) -> None:
        text = "SECTION: Only\nSECTION_SUMMARY: Partial.\nBLOCKS: 1, 2, 3\n"
        # 10 blocks but only 3 assigned — > 5% missing
        assert _parse_refine_output(text, 10) is None

    def test_remap_with_non_trivial_block_indices(self) -> None:
        """Prompt numbers remap correctly to non-sequential block indices."""
        # Original sections reference blocks 5, 2, 7 (not 0, 1, 2)
        original_sections = [
            DigestSection(title="A", block_indices=[5, 2]),
            DigestSection(title="B", block_indices=[7]),
        ]
        mapping = _build_prompt_mapping(original_sections)
        # mapping = [5, 2, 7]  (prompt 1→block 5, prompt 2→block 2, prompt 3→block 7)
        assert mapping == [5, 2, 7]

        # LLM reassigns: all 3 into one section
        llm_output = "SECTION: Merged\nSECTION_SUMMARY: All together.\nBLOCKS: 1, 2, 3\n"
        parsed = _parse_refine_output(llm_output, len(mapping))
        assert parsed is not None
        # parsed indices are 0-based prompt positions: [0, 1, 2]
        assert parsed[0].block_indices == [0, 1, 2]

        # After remapping, we get the actual block indices
        remapped = _remap_sections(parsed, mapping)
        assert remapped[0].block_indices == [5, 2, 7]

    def test_remap_reorder_across_sections(self) -> None:
        """LLM moves blocks between sections; remapping preserves real indices."""
        original_sections = [
            DigestSection(title="X", block_indices=[10, 20]),
            DigestSection(title="Y", block_indices=[30, 40]),
        ]
        mapping = _build_prompt_mapping(original_sections)
        # mapping = [10, 20, 30, 40]

        # LLM swaps: block 2 (=real 20) moves to second section
        llm_output = (
            "SECTION: First\n"
            "SECTION_SUMMARY: s1.\n"
            "BLOCKS: 1, 3\n"
            "\n"
            "SECTION: Second\n"
            "SECTION_SUMMARY: s2.\n"
            "BLOCKS: 2, 4\n"
        )
        parsed = _parse_refine_output(llm_output, len(mapping))
        assert parsed is not None
        remapped = _remap_sections(parsed, mapping)
        assert remapped[0].block_indices == [10, 30]
        assert remapped[1].block_indices == [20, 40]

    def test_preamble_before_sections_ignored(self) -> None:
        text = (
            "Here is my analysis of the blocks:\n"
            "I reorganized them as follows.\n"
            "\n"
            "SECTION: Only Section\n"
            "SECTION_SUMMARY: Everything.\n"
            "BLOCKS: 1, 2, 3\n"
        )
        result = _parse_refine_output(text, 3)
        assert result is not None
        assert len(result) == 1
        assert result[0].title == "Only Section"
