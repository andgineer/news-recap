"""Tests for the group_sections phase — parser, guardrails, and fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.tasks.group_sections import (
    _build_fallback_sections,
    _merge_single_block_sections,
    build_group_sections_prompt,
    parse_group_sections_stdout,
)
from news_recap.recap.tasks.base import RecapPipelineError


def _write_stdout(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "agent_stdout.log"
    p.write_text(text, "utf-8")
    return p


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_prompt_contains_all_block_titles() -> None:
    blocks = [
        DigestBlock(title="Block A title", article_ids=["a1"]),
        DigestBlock(title="Block B title", article_ids=["a2"]),
    ]
    prompt = build_group_sections_prompt(blocks)
    assert "1: Block A title" in prompt
    assert "2: Block B title" in prompt
    assert "2 total" in prompt


# ---------------------------------------------------------------------------
# Parser — happy path
# ---------------------------------------------------------------------------


def test_parse_happy_path(tmp_path: Path) -> None:
    text = "SECTION: Политика\n1, 2, 3\n\nSECTION: Экономика\n4, 5\n"
    path = _write_stdout(tmp_path, text)
    sections = parse_group_sections_stdout(path, n_blocks=5)

    assert len(sections) == 2
    assert sections[0].title == "Политика"
    assert sections[0].block_indices == [0, 1, 2]
    assert sections[1].title == "Экономика"
    assert sections[1].block_indices == [3, 4]


def test_parse_ignores_duplicate_block_numbers(tmp_path: Path) -> None:
    text = "SECTION: Tech\n1, 2\nSECTION: Politics\n2, 3\n"
    path = _write_stdout(tmp_path, text)
    sections = parse_group_sections_stdout(path, n_blocks=3)

    all_indices = [idx for s in sections for idx in s.block_indices]
    assert sorted(all_indices) == [0, 1, 2]


# ---------------------------------------------------------------------------
# Parser — error cases
# ---------------------------------------------------------------------------


def test_parse_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RecapPipelineError, match="not found"):
        parse_group_sections_stdout(tmp_path / "nonexistent.log", n_blocks=5)


def test_parse_raises_on_empty_stdout(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "   \n  ")
    with pytest.raises(RecapPipelineError, match="empty"):
        parse_group_sections_stdout(path, n_blocks=5)


def test_parse_raises_on_no_section_lines(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "Some random text\nwithout SECTION markers\n")
    with pytest.raises(RecapPipelineError, match="no valid SECTION"):
        parse_group_sections_stdout(path, n_blocks=5)


# ---------------------------------------------------------------------------
# Orphan handling
# ---------------------------------------------------------------------------


def test_orphan_blocks_appended_to_last_section(tmp_path: Path) -> None:
    text = "SECTION: Topic A\n1, 2\nSECTION: Topic B\n3, 4\n"
    path = _write_stdout(tmp_path, text)
    sections = parse_group_sections_stdout(path, n_blocks=6)

    all_indices = sorted(idx for s in sections for idx in s.block_indices)
    assert all_indices == [0, 1, 2, 3, 4, 5]
    assert 4 in sections[-1].block_indices
    assert 5 in sections[-1].block_indices


# ---------------------------------------------------------------------------
# Single-block section guardrail
# ---------------------------------------------------------------------------


def test_single_block_section_merged_into_neighbor(tmp_path: Path) -> None:
    text = "SECTION: Big Section\n1, 2, 3\nSECTION: Lonely\n4\nSECTION: Another Big\n5, 6\n"
    path = _write_stdout(tmp_path, text)
    sections = parse_group_sections_stdout(path, n_blocks=6)

    for s in sections:
        assert len(s.block_indices) >= 2, (
            f"Section '{s.title}' has only {len(s.block_indices)} block"
        )


def test_merge_single_block_sections_all_singles() -> None:
    """When all sections are single-block, they collapse into one."""
    sections = [
        DigestSection(title="A", block_indices=[0]),
        DigestSection(title="B", block_indices=[1]),
        DigestSection(title="C", block_indices=[2]),
    ]
    result = _merge_single_block_sections(sections)
    assert len(result) == 1
    assert sorted(result[0].block_indices) == [0, 1, 2]


# ---------------------------------------------------------------------------
# Fallback for few blocks
# ---------------------------------------------------------------------------


def test_fallback_sections_ru() -> None:
    blocks = [DigestBlock(title="A", article_ids=["x"])]
    result = _build_fallback_sections(blocks, "ru")
    assert len(result) == 1
    assert result[0].title == "Все новости"
    assert result[0].block_indices == [0]


def test_fallback_sections_en() -> None:
    blocks = [
        DigestBlock(title="A", article_ids=["x"]),
        DigestBlock(title="B", article_ids=["y"]),
    ]
    result = _build_fallback_sections(blocks, "en")
    assert len(result) == 1
    assert result[0].title == "All news"
    assert result[0].block_indices == [0, 1]


def test_fallback_sections_unknown_language() -> None:
    blocks = [DigestBlock(title="A", article_ids=["x"])]
    result = _build_fallback_sections(blocks, "fr")
    assert result[0].title == "All news"
