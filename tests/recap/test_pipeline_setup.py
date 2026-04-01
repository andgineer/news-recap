"""Tests for _find_last_digest_cutoff and _compute_article_window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import msgspec

from news_recap.recap.models import Digest, DigestArticle
from news_recap.recap.pipeline_setup import (
    _compute_article_window,
    _find_last_digest_cutoff,
    _find_resumable_pipeline,
    register_digest,
)

_DIGEST_FILENAME = "digest.json"


def _article(published_at: str) -> DigestArticle:
    return DigestArticle(
        article_id=f"a-{published_at}",
        title=f"Title {published_at}",
        url=f"https://example.com/{published_at}",
        source="test",
        published_at=published_at,
        clean_text="body",
    )


def _make_digest(
    pipeline_dir: Path,
    run_date: str,
    status: str = "completed",
    completed_phases: list[str] | None = None,
    articles: list[DigestArticle] | None = None,
) -> Digest:
    digest = Digest(
        digest_id="d-" + run_date,
        run_date=run_date,
        status=status,
        pipeline_dir=str(pipeline_dir),
        articles=articles or [],
        completed_phases=completed_phases or [],
    )
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / _DIGEST_FILENAME).write_bytes(msgspec.json.encode(digest))
    return digest


# ---------------------------------------------------------------------------
# _find_last_digest_cutoff
# ---------------------------------------------------------------------------


def test_returns_none_when_workdir_missing(tmp_path: Path) -> None:
    assert _find_last_digest_cutoff(tmp_path / "nonexistent") is None


def test_returns_none_when_no_completed_digests(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-25-080000",
        "2026-03-25",
        status="failed",
        completed_phases=["classify"],
    )
    assert _find_last_digest_cutoff(tmp_path) is None


def test_returns_none_when_completed_but_no_oneshot_phase(tmp_path: Path) -> None:
    """A --stop-after classify pipeline should not count as a fully completed digest."""
    _make_digest(
        tmp_path / "pipeline-2026-03-25-080000",
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "load_resources"],
    )
    assert _find_last_digest_cutoff(tmp_path) is None


def test_returns_latest_article_datetime(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-25-080000"
    digest = _make_digest(
        pdir,
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "enrich", "oneshot_digest", "refine_layout"],
        articles=[
            _article("2026-03-24T20:00:00+00:00"),
            _article("2026-03-25T10:30:00+00:00"),
        ],
    )
    register_digest(tmp_path, pdir, digest)
    result = _find_last_digest_cutoff(tmp_path)
    assert result == datetime(2026, 3, 25, 10, 30, tzinfo=UTC)


def test_falls_back_to_run_date_when_no_articles(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-25-080000"
    digest = _make_digest(
        pdir,
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    register_digest(tmp_path, pdir, digest)
    result = _find_last_digest_cutoff(tmp_path)
    assert result == date(2026, 3, 25)
    assert isinstance(result, date) and not isinstance(result, datetime)


def test_returns_most_recent_completed_cutoff(tmp_path: Path) -> None:
    p1 = tmp_path / "pipeline-2026-03-24-080000"
    d1 = _make_digest(
        p1,
        "2026-03-24",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-24T12:00:00+00:00")],
    )
    register_digest(tmp_path, p1, d1)
    p2 = tmp_path / "pipeline-2026-03-26-080000"
    d2 = _make_digest(
        p2,
        "2026-03-26",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-26T15:00:00+00:00")],
    )
    register_digest(tmp_path, p2, d2)
    _make_digest(
        tmp_path / "pipeline-2026-03-27-080000",
        "2026-03-27",
        status="failed",
        completed_phases=["classify"],
    )
    assert _find_last_digest_cutoff(tmp_path) == datetime(2026, 3, 26, 15, 0, tzinfo=UTC)


def test_skips_malformed_digest_files(tmp_path: Path) -> None:
    """Malformed pipeline dirs don't affect the index-based lookup."""
    bad_dir = tmp_path / "pipeline-2026-03-28-080000"
    bad_dir.mkdir(parents=True)
    (bad_dir / _DIGEST_FILENAME).write_text("not-json", "utf-8")

    pdir = tmp_path / "pipeline-2026-03-25-080000"
    digest = _make_digest(
        pdir,
        "2026-03-25",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-25T09:00:00+00:00")],
    )
    register_digest(tmp_path, pdir, digest)
    assert _find_last_digest_cutoff(tmp_path) == datetime(2026, 3, 25, 9, 0, tzinfo=UTC)


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
    assert isinstance(since, date) and not isinstance(since, datetime)


def test_compute_window_with_previous_digest(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    pdir = tmp_path / f"pipeline-{yesterday}-080000"
    digest = _make_digest(
        pdir,
        yesterday.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article(f"{yesterday}T14:30:00+00:00")],
    )
    register_digest(tmp_path, pdir, digest)
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=None)

    assert cap_days == 2
    assert since == datetime(yesterday.year, yesterday.month, yesterday.day, 14, 30, tzinfo=UTC)


def test_compute_window_caps_old_digest(tmp_path: Path) -> None:
    """When the last digest's latest article is older than the cap, the cap wins."""
    today = datetime.now(tz=UTC).date()
    old_date = today - timedelta(days=10)
    pdir = tmp_path / f"pipeline-{old_date}-080000"
    digest = _make_digest(
        pdir,
        old_date.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article(f"{old_date}T08:00:00+00:00")],
    )
    register_digest(tmp_path, pdir, digest)
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=None)
    cap_dt = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=2)

    assert cap_days == 2
    assert since == cap_dt
    assert isinstance(since, datetime)


def test_compute_window_all_articles(tmp_path: Path) -> None:
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    pdir = tmp_path / f"pipeline-{yesterday}-080000"
    digest = _make_digest(
        pdir,
        yesterday.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article(f"{yesterday}T08:00:00+00:00")],
    )
    register_digest(tmp_path, pdir, digest)
    settings = _make_settings(tmp_path, lookback_days=3)
    cap_days, since = _compute_article_window(settings, all_articles=True, max_days=None)

    assert cap_days == 3
    assert since == today - timedelta(days=3)
    assert isinstance(since, date) and not isinstance(since, datetime)


def test_compute_window_max_days_override(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, lookback_days=2)
    cap_days, since = _compute_article_window(settings, all_articles=False, max_days=5)
    today = datetime.now(tz=UTC).date()

    assert cap_days == 5
    assert since == today - timedelta(days=5)
    assert isinstance(since, date) and not isinstance(since, datetime)


def test_compute_window_digest_without_articles_returns_date(tmp_path: Path) -> None:
    """A digest whose latest_article is None yields a date (>= midnight semantics)."""
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    pdir = tmp_path / f"pipeline-{yesterday}-080000"
    digest = _make_digest(
        pdir,
        yesterday.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    register_digest(tmp_path, pdir, digest)
    settings = _make_settings(tmp_path, lookback_days=2)
    _, since = _compute_article_window(settings, all_articles=False, max_days=None)
    assert since == yesterday
    assert isinstance(since, date) and not isinstance(since, datetime)


def test_compute_window_same_day_digest_excludes_covered_articles(tmp_path: Path) -> None:
    """A digest from today should anchor since to the latest article time, not midnight."""
    today = datetime.now(tz=UTC).date()
    pdir = tmp_path / f"pipeline-{today}-100000"
    digest = _make_digest(
        pdir,
        today.isoformat(),
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[
            _article(f"{today - timedelta(days=1)}T20:00:00+00:00"),
            _article(f"{today}T09:30:00+00:00"),
        ],
    )
    register_digest(tmp_path, pdir, digest)
    settings = _make_settings(tmp_path, lookback_days=2)
    _, since = _compute_article_window(settings, all_articles=False, max_days=None)
    assert since == datetime(today.year, today.month, today.day, 9, 30, tzinfo=UTC)


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
        run_date=today.isoformat(),
        status="in_progress",
        pipeline_dir=str(tmp_path / f"pipeline-{today}-100000"),
        articles=[{"article_id": f"a-{i}"} for i in range(10)],  # type: ignore[list-item]
        completed_phases=["classify"],
    )
    pdir = tmp_path / f"pipeline-{today}-100000"
    pdir.mkdir(parents=True)
    (pdir / _DIGEST_FILENAME).write_bytes(msgspec.json.encode(digest))

    assert _find_resumable_pipeline(tmp_path, max_days=2, article_limit=5) is None
