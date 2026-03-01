"""Tests for the Deduplicate task's output parser."""

import allure

from news_recap.recap.tasks.deduplicate import parse_dedup_output

pytestmark = [
    allure.epic("Recap Pipeline"),
    allure.feature("Deduplication"),
]


class TestParseDedupOutput:
    def test_all_singles(self) -> None:
        text = "SINGLE: 1\nSINGLE: 2\nSINGLE: 3\n"
        result = parse_dedup_output(text, expected_count=3)
        assert result.merges == []
        assert sorted(result.singles) == [1, 2, 3]

    def test_one_merge(self) -> None:
        text = "MERGED: Combined news about tariffs\n1, 3\nSINGLE: 2\n"
        result = parse_dedup_output(text, expected_count=3)
        assert len(result.merges) == 1
        assert result.merges[0].merged_text == "Combined news about tariffs"
        assert result.merges[0].indices == [1, 3]
        assert result.singles == [2]

    def test_multiple_merges(self) -> None:
        text = (
            "MERGED: Iran strikes update\n"
            "1, 3, 5\n"
            "\n"
            "MERGED: Netflix price hike in EU\n"
            "2, 4\n"
            "\n"
            "SINGLE: 6\n"
        )
        result = parse_dedup_output(text, expected_count=6)
        assert len(result.merges) == 2
        assert result.merges[0].indices == [1, 3, 5]
        assert result.merges[1].indices == [2, 4]
        assert result.singles == [6]

    def test_missing_numbers_treated_as_singles(self) -> None:
        text = "MERGED: Combined\n1, 2\n"
        result = parse_dedup_output(text, expected_count=4)
        assert len(result.merges) == 1
        assert sorted(result.singles) == [3, 4]

    def test_empty_output_all_singles(self) -> None:
        result = parse_dedup_output("", expected_count=3)
        assert result.merges == []
        assert sorted(result.singles) == [1, 2, 3]

    def test_duplicate_numbers_ignored(self) -> None:
        text = "MERGED: First group\n1, 2\nMERGED: Second group tries to steal 1\n1, 3\n"
        result = parse_dedup_output(text, expected_count=3)
        assert len(result.merges) == 1
        assert result.merges[0].indices == [1, 2]
        assert 3 in result.singles

    def test_merge_with_single_number_becomes_single(self) -> None:
        text = "MERGED: Only one item\n1\nSINGLE: 2\n"
        result = parse_dedup_output(text, expected_count=2)
        assert result.merges == []
        assert sorted(result.singles) == [1, 2]

    def test_ignores_invalid_numbers(self) -> None:
        text = "SINGLE: 1\nSINGLE: 99\nSINGLE: 2\n"
        result = parse_dedup_output(text, expected_count=2)
        assert sorted(result.singles) == [1, 2]

    def test_blank_lines_between_sections(self) -> None:
        text = "\n\nMERGED: Group A\n\n1, 2\n\n\nSINGLE: 3\n\n"
        result = parse_dedup_output(text, expected_count=3)
        assert len(result.merges) == 1
        assert result.merges[0].indices == [1, 2]
        assert result.singles == [3]
