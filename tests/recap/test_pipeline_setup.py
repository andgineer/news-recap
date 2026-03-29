"""Tests for _find_last_completed_digest_date and _compute_article_window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import msgspec

from news_recap.recap.models import Digest
from news_recap.recap.pipeline_setup import (
    _compute_article_window,
    _find_last_completed_digest_date,
    _find_resumable_pipeline,
)

_DIGEST_FILENAME = "digest.json"


def _make_digest(
    pipeline_dir: Path,
    business_date: str,
    status: str = "completed",
    completed_phases: list[str] | None = None,
) -> None:
    digest = Digest(
        digest_id="d-" + business_date,
        business_date=business_date,
        status=status,
        pipeline_dir=str(pipeline_dir),
        articles=[],
        completed_phases=completed_phases or [],
    )
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / _DIGEST_FILENAME).write_bytes(msgspec.json.encode(digest))


# ---------------------------------------------------------------------------
# _find_last_completed_digest_date
# ---------------------------------------------------------------------------


def test_returns_none_when_workdir_missing(tmp_path: Path) -> None:
    assert _find_last_completed_digest_date(tmp_path / "nonexistent") is None


def test_returns_none_when_no_completed_digests(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-25-080000",
        "2026-03-25",
        status="failed",
        completed_phases=["classify"],
    )
    assert _find_last_completed_digest_date(tmp_path) is None


def test_returns_none_when_completed_but_no_oneshot_phase(tmp_path: Path) -> None:
    """A --stop-after classify pipeline should not count as a fully completed digest."""
    _make_digest(
        tmp_path / "pipeline-2026-03-25-080000",
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "load_resources"],
    )
    assert _find_last_completed_digest_date(tmp_path) is None


def test_returns_date_of_completed_digest(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-25-080000",
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "enrich", "oneshot_digest", "refine_layout"],
    )
    assert _find_last_completed_digest_date(tmp_path) == date(2026, 3, 25)


def test_returns_most_recent_completed_date(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-24-080000",
        "2026-03-24",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    _make_digest(
        tmp_path / "pipeline-2026-03-26-080000",
        "2026-03-26",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    _make_digest(
        tmp_path / "pipeline-2026-03-27-080000",
        "2026-03-27",
        status="failed",
        completed_phases=["classify"],
    )
    assert _find_last_completed_digest_date(tmp_path) == date(2026, 3, 26)


def test_skips_malformed_digest_files(tmp_path: Path) -> None:
    bad_dir = tmp_path / "pipeline-2026-03-28-080000"
    bad_dir.mkdir(parents=True)
    (bad_dir / _DIGEST_FILENAME).write_text("not-json", "utf-8")

    _make_digest(
        tmp_path / "pipeline-2026-03-25-080000",
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    assert _find_last_completed_digest_date(tmp_path) == date(2026, 3, 25)


# ---------------------------------------------------------------------------
# _compute_article_window
# ---------------------------------------------------------------------------


def _make_settings(workdir_root: Path, lookback_days: int = 2) -> MagicMock:
    settings = MagicMock()
    settings.ingestion.digest_lookback_days = lookback_days
    settings.orchestrator.workdir_root = workdir_root
    return settings


def test_compute_window_no_previous_digest(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=None)
    today = datetime.now(tz=UTC).date()

    assert cap_days == 2
    assert since == today - timedelta(days=2)


def test_compute_window_with_previous_digest(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    _make_digest(
        tmp_path / f"pipeline-{yesterday}-080000",
        yesterday.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=None)

    assert cap_days == 2
    assert since == yesterday


def test_compute_window_caps_old_digest(tmp_path: Path) -> None:
    """When the last digest is older than the cap, the cap wins."""
    today = datetime.now(tz=UTC).date()
    old_date = today - timedelta(days=10)
    _make_digest(
        tmp_path / f"pipeline-{old_date}-080000",
        old_date.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=None)

    assert cap_days == 2
    assert since == today - timedelta(days=2)


def test_compute_window_all_articles(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    _make_digest(
        tmp_path / f"pipeline-{yesterday}-080000",
        yesterday.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    settings = _make_settings(tmp_path, lookback_days=3)
    cap_days, since = _compute_article_window(settings, all_articles=True, max_days=None)

    assert cap_days == 3
    assert since == today - timedelta(days=3)


def test_compute_window_max_days_override(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=5)
    today = datetime.now(tz=UTC).date()

    assert cap_days == 5
    assert since == today - timedelta(days=5)


# ---------------------------------------------------------------------------
# _find_resumable_pipeline
# ---------------------------------------------------------------------------


def test_resumable_returns_none_when_workdir_missing(tmp_path: Path) -> None:
    assert (
        _find_resumable_pipeline(tmp_path / "nonexistent", max_days=2, article_limit=None) is None
    )


def test_resumable_finds_incomplete_pipeline_within_window(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    _make_digest(
        tmp_path / f"pipeline-{today}-100000",
        today.isoformat(),
        status="in_progress",
        completed_phases=["classify"],
    )
    result = _find_resumable_pipeline(tmp_path, max_days=2, article_limit=None)
    assert result is not None
    assert result.name == f"pipeline-{today}-100000"


def test_resumable_stops_at_completed_pipeline(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    _make_digest(
        tmp_path / f"pipeline-{today}-100000",
        today.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    assert _find_resumable_pipeline(tmp_path, max_days=2, article_limit=None) is None


def test_resumable_ignores_incomplete_older_than_completed(tmp_path: Path) -> None:
    """An incomplete pipeline older than a completed one is not considered."""
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    _make_digest(
        tmp_path / f"pipeline-{today}-100000",
        today.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    _make_digest(
        tmp_path / f"pipeline-{yesterday}-080000",
        yesterday.isoformat(),
        status="in_progress",
        completed_phases=["classify"],
    )
    assert _find_resumable_pipeline(tmp_path, max_days=2, article_limit=None) is None


def test_resumable_skips_pipelines_outside_window(tmp_path: Path) -> None:
    old_date = datetime.now(tz=UTC).date() - timedelta(days=5)
    _make_digest(
        tmp_path / f"pipeline-{old_date}-100000",
        old_date.isoformat(),
        status="in_progress",
        completed_phases=["classify"],
    )
    assert _find_resumable_pipeline(tmp_path, max_days=2, article_limit=None) is None


def test_resumable_skips_article_limit_mismatch(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    digest = Digest(
        digest_id="d-test",
        business_date=today.isoformat(),
        status="in_progress",
        pipeline_dir=str(tmp_path / f"pipeline-{today}-100000"),
        articles=[{"article_id": f"a-{i}"} for i in range(10)],  # type: ignore[list-item]
        completed_phases=["classify"],
    )
    pdir = tmp_path / f"pipeline-{today}-100000"
    pdir.mkdir(parents=True)
    (pdir / _DIGEST_FILENAME).write_bytes(msgspec.json.encode(digest))

    assert _find_resumable_pipeline(tmp_path, max_days=2, article_limit=5) is None
