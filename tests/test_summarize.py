"""Tests for the summarize phase — parser and prompt builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.tasks.base import RecapPipelineError
from news_recap.recap.tasks.summarize import (
    build_summarize_prompt,
    parse_summarize_stdout,
)


def _write_stdout(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "agent_stdout.log"
    p.write_text(text, "utf-8")
    return p


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_prompt_includes_section_titles_and_blocks() -> None:
    sections = [
        DigestSection(title="Политика", block_indices=[0, 1]),
        DigestSection(title="Tech", block_indices=[2]),
    ]
    blocks = [
        DigestBlock(title="Block about elections", article_ids=["a1"]),
        DigestBlock(title="Block about diplomacy", article_ids=["a2"]),
        DigestBlock(title="Block about AI", article_ids=["a3"]),
    ]
    prompt = build_summarize_prompt(sections, blocks, "ru")

    assert "## Политика" in prompt
    assert "Block about elections" in prompt
    assert "Block about diplomacy" in prompt
    assert "## Tech" in prompt
    assert "Block about AI" in prompt
    assert "ru" in prompt


# ---------------------------------------------------------------------------
# Parser — happy path
# ---------------------------------------------------------------------------


def test_parse_extracts_content_between_markers(tmp_path: Path) -> None:
    text = (
        "Some preamble text\n"
        "SUMMARY_START\n"
        "Главные линии дня:\n"
        "- Украина и дипломатия\n"
        "- AI и рынки\n"
        "SUMMARY_END\n"
        "Some trailing text\n"
    )
    path = _write_stdout(tmp_path, text)
    result = parse_summarize_stdout(path)

    assert "Главные линии дня:" in result
    assert "- Украина и дипломатия" in result
    assert "- AI и рынки" in result
    assert "SUMMARY_START" not in result
    assert "SUMMARY_END" not in result
    assert "preamble" not in result


def test_parse_strips_whitespace(tmp_path: Path) -> None:
    text = "SUMMARY_START\n\n  Day summary text  \n\nSUMMARY_END\n"
    path = _write_stdout(tmp_path, text)
    result = parse_summarize_stdout(path)
    assert result == "Day summary text"


# ---------------------------------------------------------------------------
# Parser — error cases
# ---------------------------------------------------------------------------


def test_parse_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RecapPipelineError, match="not found"):
        parse_summarize_stdout(tmp_path / "nonexistent.log")


def test_parse_raises_on_empty_stdout(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "   \n  ")
    with pytest.raises(RecapPipelineError, match="empty"):
        parse_summarize_stdout(path)


def test_parse_raises_on_missing_start_marker(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "Some text\nSUMMARY_END\n")
    with pytest.raises(RecapPipelineError, match="markers"):
        parse_summarize_stdout(path)


def test_parse_raises_on_missing_end_marker(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "SUMMARY_START\nSome text\n")
    with pytest.raises(RecapPipelineError, match="markers"):
        parse_summarize_stdout(path)


def test_parse_raises_on_reversed_markers(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "SUMMARY_END\ntext\nSUMMARY_START\n")
    with pytest.raises(RecapPipelineError, match="markers"):
        parse_summarize_stdout(path)


def test_parse_raises_on_empty_content_between_markers(tmp_path: Path) -> None:
    path = _write_stdout(tmp_path, "SUMMARY_START\n  \nSUMMARY_END\n")
    with pytest.raises(RecapPipelineError, match="empty"):
        parse_summarize_stdout(path)
