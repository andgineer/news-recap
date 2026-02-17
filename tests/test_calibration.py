from pathlib import Path

from news_recap.ingestion.dedup.calibration import load_golden_pairs


def test_golden_set_fixture_exists_and_has_expected_size() -> None:
    path = Path("tests/fixtures/golden_set.csv")
    pairs = load_golden_pairs(path)
    assert len(pairs) >= 240
