"""Tests for the oneshot_digest task: parser, index building, and coverage check."""

from __future__ import annotations


from news_recap.recap.tasks.oneshot_digest import _parse_output, _parse_nums


# ---------------------------------------------------------------------------
# _parse_nums
# ---------------------------------------------------------------------------


def test_parse_nums_basic() -> None:
    assert _parse_nums("1, 2, 3") == ["1", "2", "3"]


def test_parse_nums_strips_whitespace() -> None:
    assert _parse_nums("  5 , 10 , 15  ") == ["5", "10", "15"]


def test_parse_nums_ignores_non_digits() -> None:
    assert _parse_nums("1, abc, 3") == ["1", "3"]


# ---------------------------------------------------------------------------
# _parse_output — basic structure
# ---------------------------------------------------------------------------

_SIMPLE_OUTPUT = """\
SECTION: Politics
SECTION_SUMMARY: A brief overview of political events.
BLOCK: Election results
SUMMARY: Candidates competed in a tight race.
ARTICLES: 1, 3
BLOCK: Budget talks
SUMMARY: Parliament debated the annual budget.
ARTICLES: 2, 4
SECTION: Technology
SECTION_SUMMARY: Tech news this week.
BLOCK: AI breakthroughs
SUMMARY: New models released.
ARTICLES: 5
EXCLUDED: 6, 7
"""


def test_parse_output_sections() -> None:
    sections, excluded = _parse_output(_SIMPLE_OUTPUT)
    assert len(sections) == 2
    assert sections[0].title == "Politics"
    assert sections[1].title == "Technology"


def test_parse_output_section_summaries() -> None:
    sections, _ = _parse_output(_SIMPLE_OUTPUT)
    assert sections[0].summary == "A brief overview of political events."
    assert sections[1].summary == "Tech news this week."


def test_parse_output_blocks() -> None:
    sections, _ = _parse_output(_SIMPLE_OUTPUT)
    assert len(sections[0].blocks) == 2
    assert sections[0].blocks[0].title == "Election results"
    assert sections[0].blocks[1].title == "Budget talks"
    assert len(sections[1].blocks) == 1


def test_parse_output_block_summaries() -> None:
    sections, _ = _parse_output(_SIMPLE_OUTPUT)
    assert sections[0].blocks[0].summary == "Candidates competed in a tight race."
    assert sections[0].blocks[1].summary == "Parliament debated the annual budget."


def test_parse_output_article_nums() -> None:
    sections, _ = _parse_output(_SIMPLE_OUTPUT)
    assert sections[0].blocks[0].article_nums == ["1", "3"]
    assert sections[0].blocks[1].article_nums == ["2", "4"]
    assert sections[1].blocks[0].article_nums == ["5"]


def test_parse_output_excluded() -> None:
    _, excluded = _parse_output(_SIMPLE_OUTPUT)
    assert excluded == ["6", "7"]


# ---------------------------------------------------------------------------
# _parse_output — case-insensitive matching
# ---------------------------------------------------------------------------

_MIXED_CASE = """\
section: Science
section_summary: Science summary.
block: Physics
summary: Quantum experiments.
articles: 1
"""


def test_parse_output_case_insensitive() -> None:
    sections, _ = _parse_output(_MIXED_CASE)
    assert len(sections) == 1
    assert sections[0].title == "Science"
    assert sections[0].blocks[0].title == "Physics"
    assert sections[0].blocks[0].article_nums == ["1"]


# ---------------------------------------------------------------------------
# _parse_output — multi-line summaries
# ---------------------------------------------------------------------------

_MULTILINE_SUMMARY = """\
SECTION: World
SECTION_SUMMARY: First line of section summary.
Second line of section summary.
BLOCK: Floods
SUMMARY: First line.
Second line.
ARTICLES: 1
"""


def test_parse_output_multiline_block_summary() -> None:
    sections, _ = _parse_output(_MULTILINE_SUMMARY)
    assert "First line." in sections[0].blocks[0].summary
    assert "Second line." in sections[0].blocks[0].summary


def test_parse_output_multiline_section_summary() -> None:
    sections, _ = _parse_output(_MULTILINE_SUMMARY)
    assert "First line of section summary." in sections[0].summary
    assert "Second line of section summary." in sections[0].summary


# ---------------------------------------------------------------------------
# _parse_output — continuation ARTICLES lines
# ---------------------------------------------------------------------------

_CONT_ARTICLES = """\
SECTION: S
BLOCK: B
SUMMARY: Summary.
ARTICLES: 1, 2
3, 4
EXCLUDED: 5
"""


def test_parse_output_continuation_articles() -> None:
    sections, _ = _parse_output(_CONT_ARTICLES)
    assert sections[0].blocks[0].article_nums == ["1", "2", "3", "4"]


# ---------------------------------------------------------------------------
# _parse_output — discards block before section
# ---------------------------------------------------------------------------

_BLOCK_BEFORE_SECTION = """\
BLOCK: Orphan block
SUMMARY: Should be ignored.
ARTICLES: 1
SECTION: Real section
BLOCK: Valid block
SUMMARY: OK.
ARTICLES: 2
"""


def test_parse_output_discards_block_before_section() -> None:
    sections, _ = _parse_output(_BLOCK_BEFORE_SECTION)
    assert len(sections) == 1
    assert len(sections[0].blocks) == 1
    assert sections[0].blocks[0].title == "Valid block"


# ---------------------------------------------------------------------------
# _parse_output — section with no valid blocks is dropped
# ---------------------------------------------------------------------------

_EMPTY_SECTION = """\
SECTION: Empty
SECTION_SUMMARY: No blocks.
SECTION: Full
BLOCK: Has articles
SUMMARY: Present.
ARTICLES: 1
"""


def test_parse_output_drops_section_with_no_blocks() -> None:
    sections, _ = _parse_output(_EMPTY_SECTION)
    assert len(sections) == 1
    assert sections[0].title == "Full"


# ---------------------------------------------------------------------------
# _parse_output — block without articles is dropped
# ---------------------------------------------------------------------------

_BLOCK_NO_ARTICLES = """\
SECTION: S
BLOCK: No articles block
SUMMARY: Has summary but no ARTICLES line.
BLOCK: Good block
SUMMARY: Has articles.
ARTICLES: 1
"""


def test_parse_output_drops_block_without_articles() -> None:
    sections, _ = _parse_output(_BLOCK_NO_ARTICLES)
    assert len(sections[0].blocks) == 1
    assert sections[0].blocks[0].title == "Good block"


# ---------------------------------------------------------------------------
# num_to_id + coverage check integration
# ---------------------------------------------------------------------------


def test_num_to_id_resolution() -> None:
    """Verify that article numbers map correctly to article IDs after parsing."""
    output = """\
SECTION: S
BLOCK: B
SUMMARY: Summary.
ARTICLES: 1, 2
"""
    sections, _ = _parse_output(output)
    num_to_id = {"1": "art-001", "2": "art-002", "3": "art-003"}
    article_ids = [num_to_id[n] for n in sections[0].blocks[0].article_nums if n in num_to_id]
    assert article_ids == ["art-001", "art-002"]


def test_excluded_nums_resolved_correctly() -> None:
    output = "EXCLUDED: 1, 3\n"
    _, excluded = _parse_output(output)
    num_to_id = {"1": "art-001", "2": "art-002", "3": "art-003"}
    excluded_ids = {num_to_id[n] for n in excluded if n in num_to_id}
    assert excluded_ids == {"art-001", "art-003"}
