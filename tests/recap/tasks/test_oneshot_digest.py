"""Tests for the oneshot_digest task: parser, index building, and coverage check."""

from __future__ import annotations


from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.tasks.oneshot_digest import _dedup_blocks, _parse_nums, _parse_output


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


# ---------------------------------------------------------------------------
# _dedup_blocks
# ---------------------------------------------------------------------------


def _b(title: str, ids: list[str]) -> DigestBlock:
    return DigestBlock(title=title, article_ids=ids)


def _s(title: str, indices: list[int], summary: str = "") -> DigestSection:
    return DigestSection(title=title, block_indices=indices, summary=summary)


def test_dedup_removes_exact_duplicates() -> None:
    blocks = [
        _b("Block A", ["a1", "a2"]),
        _b("Block B", ["b1"]),
        _b("Block A copy", ["a1", "a2"]),
    ]
    sections = [_s("S", [0, 1, 2])]

    new_blocks, new_sections = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 2
    article_sets = [frozenset(b.article_ids) for b in new_blocks]
    assert frozenset(["a1", "a2"]) in article_sets
    assert frozenset(["b1"]) in article_sets


def test_dedup_keeps_longer_title() -> None:
    blocks = [
        _b("Short", ["x1", "x2"]),
        _b("Much longer and more informative title", ["x1", "x2"]),
    ]
    sections = [_s("S", [0, 1])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 1
    assert new_blocks[0].title == "Much longer and more informative title"


def test_dedup_prefers_earlier_on_tie() -> None:
    blocks = [
        _b("Same len A", ["x1"]),
        _b("Same len B", ["x1"]),
    ]
    sections = [_s("S", [0, 1])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 1
    assert new_blocks[0].title == "Same len A"


def test_dedup_preserves_article_id_union() -> None:
    blocks = [
        _b("A", ["a1", "a2"]),
        _b("B", ["b1"]),
        _b("A dup", ["a2", "a1"]),
        _b("C", ["c1", "c2"]),
    ]
    sections = [_s("S", [0, 1, 2, 3])]

    union_before = {aid for b in blocks for aid in b.article_ids}
    new_blocks, _ = _dedup_blocks(blocks, sections)
    union_after = {aid for b in new_blocks for aid in b.article_ids}

    assert union_before == union_after


def test_dedup_rewrites_block_indices() -> None:
    blocks = [
        _b("A", ["a1"]),
        _b("B", ["b1"]),
        _b("A dup", ["a1"]),
        _b("C", ["c1"]),
    ]
    sections = [
        _s("S1", [0, 1], summary="summary 1"),
        _s("S2", [2, 3], summary="summary 2"),
    ]

    new_blocks, new_sections = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 3

    for sec in new_sections:
        for idx in sec.block_indices:
            assert 0 <= idx < len(new_blocks), f"index {idx} out of range"


def test_dedup_preserves_section_order_and_summaries() -> None:
    blocks = [
        _b("A", ["a1"]),
        _b("B", ["b1"]),
        _b("A dup", ["a1"]),
    ]
    sections = [
        _s("First", [0, 1], summary="first summary"),
        _s("Second", [2], summary="second summary"),
    ]

    _, new_sections = _dedup_blocks(blocks, sections)

    assert [s.title for s in new_sections] == ["First", "Second"]
    assert new_sections[0].summary == "first summary"
    assert new_sections[1].summary == "second summary"


def test_dedup_deduplicates_section_indices() -> None:
    """When two old blocks in the same section collapse to one, the index appears once."""
    blocks = [
        _b("A", ["a1"]),
        _b("A dup", ["a1"]),
        _b("B", ["b1"]),
    ]
    sections = [_s("S", [0, 1, 2])]

    _, new_sections = _dedup_blocks(blocks, sections)

    assert len(set(new_sections[0].block_indices)) == len(new_sections[0].block_indices)


def test_dedup_no_duplicates_is_noop() -> None:
    blocks = [
        _b("A", ["a1"]),
        _b("B", ["b1"]),
        _b("C", ["c1"]),
    ]
    sections = [_s("S", [0, 1, 2])]

    new_blocks, new_sections = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 3
    assert new_sections[0].block_indices == [0, 1, 2]


def test_dedup_order_insensitive_article_ids() -> None:
    """article_ids in different order are still exact duplicates."""
    blocks = [
        _b("A", ["x2", "x1", "x3"]),
        _b("A alt", ["x1", "x3", "x2"]),
    ]
    sections = [_s("S", [0, 1])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 1


def test_dedup_no_duplicate_article_ids_within_block() -> None:
    """Repeated article_ids within a single block are treated correctly."""
    blocks = [
        _b("A", ["x1", "x1", "x2"]),
        _b("A dup", ["x1", "x2"]),
    ]
    sections = [_s("S", [0, 1])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 1


def test_dedup_empty_blocks() -> None:
    new_blocks, new_sections = _dedup_blocks([], [])

    assert new_blocks == []
    assert new_sections == []


# ---------------------------------------------------------------------------
# _dedup_blocks — subset absorption
# ---------------------------------------------------------------------------


def test_dedup_absorbs_strict_subset() -> None:
    """Block whose articles are a strict subset of another is removed."""
    blocks = [
        _b("Small block", ["a1", "a2"]),
        _b("Big block covering more", ["a1", "a2", "a3"]),
        _b("Unrelated", ["b1"]),
    ]
    sections = [_s("S", [0, 1, 2])]

    new_blocks, new_sections = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 2
    titles = {b.title for b in new_blocks}
    assert "Big block covering more" in titles
    assert "Unrelated" in titles
    assert "Small block" not in titles


def test_dedup_subset_preserves_article_coverage() -> None:
    """No article IDs are lost when a subset block is absorbed."""
    blocks = [
        _b("Subset", ["a1", "a2"]),
        _b("Superset", ["a1", "a2", "a3"]),
        _b("Other", ["b1"]),
    ]
    sections = [_s("S", [0, 1, 2])]

    union_before = {aid for b in blocks for aid in b.article_ids}
    new_blocks, _ = _dedup_blocks(blocks, sections)
    union_after = {aid for b in new_blocks for aid in b.article_ids}

    assert union_before == union_after


def test_dedup_subset_picks_smallest_superset() -> None:
    """When a block is a subset of a non-chain superset, the smallest superset wins."""
    blocks = [
        _b("Tiny", ["a1"]),
        _b("Medium", ["a1", "a2"]),
        _b("Large", ["a1", "a2", "a3", "a4"]),
        _b("Unrelated", ["b1", "a1"]),
    ]
    sections = [_s("S", [0, 1, 2, 3])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    # Tiny ⊂ Medium ⊂ Large (chain → only Large survives from that chain)
    # Unrelated shares a1 with Tiny but is not a superset (has b1, lacks a2)
    assert len(new_blocks) == 2
    titles = {b.title for b in new_blocks}
    assert "Large" in titles
    assert "Unrelated" in titles


def test_dedup_subset_rewrites_indices() -> None:
    """Section indices point to the superset block after absorption."""
    blocks = [
        _b("Sub", ["a1"]),
        _b("Super", ["a1", "a2"]),
        _b("Other", ["b1"]),
    ]
    sections = [
        _s("S1", [0, 2], summary="s1"),
        _s("S2", [1], summary="s2"),
    ]

    new_blocks, new_sections = _dedup_blocks(blocks, sections)

    for sec in new_sections:
        for idx in sec.block_indices:
            assert 0 <= idx < len(new_blocks)


def test_dedup_subset_does_not_absorb_equal_sets() -> None:
    """Equal sets are handled by exact-dedup, not subset absorption."""
    blocks = [
        _b("Version A", ["a1", "a2"]),
        _b("Version B — longer title wins", ["a1", "a2"]),
    ]
    sections = [_s("S", [0, 1])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 1
    assert new_blocks[0].title == "Version B — longer title wins"


def test_dedup_chained_subsets() -> None:
    """A ⊂ B ⊂ C — both A and B are removed, only C remains."""
    blocks = [
        _b("Smallest", ["a1"]),
        _b("Middle", ["a1", "a2"]),
        _b("Largest", ["a1", "a2", "a3"]),
    ]
    sections = [_s("S", [0, 1, 2])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 1
    assert new_blocks[0].title == "Largest"


def test_dedup_no_absorption_for_partial_overlap() -> None:
    """Overlapping but non-subset blocks are both kept."""
    blocks = [
        _b("Block A", ["a1", "a2", "a3"]),
        _b("Block B", ["a2", "a3", "a4"]),
    ]
    sections = [_s("S", [0, 1])]

    new_blocks, _ = _dedup_blocks(blocks, sections)

    assert len(new_blocks) == 2
