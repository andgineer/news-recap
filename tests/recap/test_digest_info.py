"""Tests for _list_completed_digests and DigestInfoController."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec

from news_recap.recap.digest_info import DigestInfoController
from news_recap.recap.models import Digest, DigestArticle
from news_recap.recap.pipeline_setup import (
    _find_digest_pipeline_dir,
    _list_completed_digests,
    gc_old_pipelines,
)

_DIGEST_FILENAME = "digest.json"


def _make_digest(
    pipeline_dir: Path,
    business_date: str,
    status: str = "completed",
    completed_phases: list[str] | None = None,
    articles: list[DigestArticle] | None = None,
) -> None:
    digest = Digest(
        digest_id="d-" + business_date,
        business_date=business_date,
        status=status,
        pipeline_dir=str(pipeline_dir),
        articles=articles or [],
        completed_phases=completed_phases or [],
    )
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / _DIGEST_FILENAME).write_bytes(msgspec.json.encode(digest))


def _article(published_at: str) -> DigestArticle:
    return DigestArticle(
        article_id=f"a-{published_at}",
        title=f"Title {published_at}",
        url=f"https://example.com/{published_at}",
        source="test",
        published_at=published_at,
        clean_text="body",
    )


# ---------------------------------------------------------------------------
# _list_completed_digests
# ---------------------------------------------------------------------------


def test_list_empty_workdir(tmp_path: Path) -> None:
    assert _list_completed_digests(tmp_path / "nonexistent") == []


def test_list_skips_failed_and_running(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="failed",
        completed_phases=["classify"],
    )
    _make_digest(
        tmp_path / "pipeline-2026-03-02-100000",
        "2026-03-02",
        status="running",
        completed_phases=["classify"],
    )
    assert _list_completed_digests(tmp_path) == []


def test_list_skips_incomplete_phases(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "enrich"],
    )
    assert _list_completed_digests(tmp_path) == []


def test_list_returns_completed_digests(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[
            _article("2026-02-28T20:00:00+00:00"),
            _article("2026-03-01T10:00:00+00:00"),
        ],
    )
    result = _list_completed_digests(tmp_path)
    assert len(result) == 1
    s = result[0]
    assert s.digest_id == 1
    assert s.business_date == date(2026, 3, 1)
    assert s.article_count == 2
    assert s.earliest_article == datetime(2026, 2, 28, 20, 0, tzinfo=UTC)
    assert s.latest_article == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    assert s.pipeline_dir_name == "pipeline-2026-03-01-100000"


def test_list_newest_first(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    _make_digest(
        tmp_path / "pipeline-2026-03-02-100000",
        "2026-03-02",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-02T10:00:00+00:00")],
    )
    result = _list_completed_digests(tmp_path)
    assert len(result) == 2
    assert result[0].digest_id == 1
    assert result[0].business_date == date(2026, 3, 2)
    assert result[1].digest_id == 2
    assert result[1].business_date == date(2026, 3, 1)


def test_list_zero_article_digest(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[],
    )
    result = _list_completed_digests(tmp_path)
    assert len(result) == 1
    assert result[0].article_count == 0
    assert result[0].earliest_article is None
    assert result[0].latest_article is None


# ---------------------------------------------------------------------------
# DigestInfoController.digest_info
# ---------------------------------------------------------------------------


def test_digest_info_empty_workdir(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.orchestrator.workdir_root = tmp_path / "nonexistent"
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().digest_info()
    assert lines == ["No digests found."]


def test_digest_info_shows_digests_and_gap(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    _make_digest(
        workdir / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[
            _article("2026-02-27T06:00:00+00:00"),
            _article("2026-02-28T12:15:00+00:00"),
        ],
    )
    _make_digest(
        workdir / "pipeline-2026-03-02-100000",
        "2026-03-02",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[
            _article("2026-02-28T20:12:00+00:00"),
            _article("2026-03-01T14:30:00+00:00"),
        ],
    )

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().digest_info()

    assert lines[0] == "Digests (newest first):"
    assert "#1" in lines[1]
    assert "2026-03-02" in lines[1]
    assert "2 articles" in lines[1]
    assert "#2" in lines[2]
    assert "2026-03-01" in lines[2]
    assert "2 articles" in lines[2]

    assert "Uncovered periods:" in lines
    gap_idx = lines.index("Uncovered periods:")
    assert "2026-02-28 12:15 .. 2026-02-28 20:12" in lines[gap_idx + 1]


def test_digest_info_no_gap_when_overlapping(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    _make_digest(
        workdir / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[
            _article("2026-02-27T06:00:00+00:00"),
            _article("2026-02-28T20:00:00+00:00"),
        ],
    )
    _make_digest(
        workdir / "pipeline-2026-03-02-100000",
        "2026-03-02",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[
            _article("2026-02-28T08:00:00+00:00"),
            _article("2026-03-01T14:30:00+00:00"),
        ],
    )

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().digest_info()

    assert "Uncovered periods:" not in lines


def test_digest_info_zero_article_excluded_from_gaps(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    _make_digest(
        workdir / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-02-28T12:00:00+00:00")],
    )
    _make_digest(
        workdir / "pipeline-2026-03-02-100000",
        "2026-03-02",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[],
    )
    _make_digest(
        workdir / "pipeline-2026-03-03-100000",
        "2026-03-03",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-03T08:00:00+00:00")],
    )

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().digest_info()

    assert "Uncovered periods:" in lines
    gap_idx = lines.index("Uncovered periods:")
    assert "2026-02-28 12:00 .. 2026-03-03 08:00" in lines[gap_idx + 1]


# ---------------------------------------------------------------------------
# _find_digest_pipeline_dir
# ---------------------------------------------------------------------------


def test_find_digest_by_id(tmp_path: Path) -> None:
    _make_digest(
        tmp_path / "pipeline-2026-03-01-100000",
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    _make_digest(
        tmp_path / "pipeline-2026-03-02-100000",
        "2026-03-02",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    assert _find_digest_pipeline_dir(tmp_path, 1) == tmp_path / "pipeline-2026-03-02-100000"
    assert _find_digest_pipeline_dir(tmp_path, 2) == tmp_path / "pipeline-2026-03-01-100000"
    assert _find_digest_pipeline_dir(tmp_path, 99) is None


# ---------------------------------------------------------------------------
# gc_old_pipelines
# ---------------------------------------------------------------------------


def test_gc_old_pipelines_removes_old(tmp_path: Path) -> None:
    today = date.today()
    old_date = today - timedelta(days=10)
    recent_date = today - timedelta(days=1)

    old_dir = tmp_path / f"pipeline-{old_date.isoformat()}-100000"
    old_dir.mkdir(parents=True)
    (old_dir / "digest.json").write_text("{}")

    recent_dir = tmp_path / f"pipeline-{recent_date.isoformat()}-100000"
    recent_dir.mkdir(parents=True)
    (recent_dir / "digest.json").write_text("{}")

    deleted = gc_old_pipelines(tmp_path, keep_days=7)
    assert len(deleted) == 1
    assert deleted[0] == old_dir
    assert not old_dir.exists()
    assert recent_dir.exists()


def test_gc_old_pipelines_noop_when_missing(tmp_path: Path) -> None:
    assert gc_old_pipelines(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_digest_cli_help() -> None:
    from click.testing import CliRunner

    from news_recap.main import news_recap

    runner = CliRunner()
    result = runner.invoke(news_recap, ["digest", "--help"])
    assert result.exit_code == 0
    assert "completed digests" in result.output.lower()
