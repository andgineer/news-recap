"""Tests for digest index, _list_completed_digests, and DigestInfoController."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec

from news_recap.recap.digest_info import (
    DigestInfoController,
    _human_elapsed,
    _human_size,
    _smart_period,
)
from news_recap.recap.models import Digest, DigestArticle
from news_recap.recap.pipeline_setup import (
    DigestIndexEntry,
    _find_digest_pipeline_dir,
    _find_latest_digest_pipeline_dir,
    _list_completed_digests,
    _load_digest_index,
    _next_free_id,
    _parse_pipeline_start,
    gc_old_pipelines,
    register_digest,
    unregister_digest,
)

_DIGEST_FILENAME = "digest.json"


def _latest_published(articles: list[DigestArticle]) -> str | None:
    if not articles:
        return None
    return max(a.published_at for a in articles)


def _make_digest(
    pipeline_dir: Path,
    run_date: str,
    status: str = "completed",
    completed_phases: list[str] | None = None,
    articles: list[DigestArticle] | None = None,
    coverage_start: str | None = None,
) -> Digest:
    arts = articles or []
    digest = Digest(
        digest_id="d-" + run_date,
        run_date=run_date,
        status=status,
        pipeline_dir=str(pipeline_dir),
        articles=arts,
        completed_phases=completed_phases or [],
        coverage_start=coverage_start,
        coverage_end=_latest_published(arts),
    )
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / _DIGEST_FILENAME).write_bytes(msgspec.json.encode(digest))
    return digest


def _make_and_register(
    workdir: Path,
    dir_name: str,
    run_date: str,
    articles: list[DigestArticle] | None = None,
    coverage_start: str | None = None,
) -> Digest:
    """Create a completed digest on disk and register it in the index."""
    pdir = workdir / dir_name
    digest = _make_digest(
        pdir,
        run_date,
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=articles,
        coverage_start=coverage_start,
    )
    register_digest(workdir, pdir, digest)
    return digest


def _article(published_at: str) -> DigestArticle:
    return DigestArticle(
        article_id=f"a-{published_at}",
        title=f"Title {published_at}",
        url=f"https://example.com/{published_at}",
        source="test",
        published_at=published_at,
        clean_text="body",
    )


def _local_str(iso: str) -> str:
    """Format a UTC ISO timestamp as local ``YYYY-MM-DD HH:MM``."""
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_smart_period_same_day() -> None:
    e = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    l = datetime(2026, 3, 1, 8, 30, tzinfo=UTC)
    el = e.astimezone()
    ll = l.astimezone()
    result = _smart_period(e, l)
    assert el.strftime("%H:%M") in result
    assert ll.strftime("%H:%M") in result
    assert ".." in result


def test_smart_period_different_days() -> None:
    e = datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
    l = datetime(2026, 1, 17, 8, 30, tzinfo=UTC)
    el = e.astimezone()
    ll = l.astimezone()
    result = _smart_period(e, l)
    assert el.strftime("%Y-%m-%d") in result
    assert ll.strftime("%Y-%m-%d") in result
    assert ".." in result


def test_smart_period_none() -> None:
    assert _smart_period(None, None) == "—"


def test_human_elapsed_seconds() -> None:
    assert _human_elapsed(45) == "45s"


def test_human_elapsed_minutes() -> None:
    assert _human_elapsed(125) == "2m 5s"


def test_human_elapsed_hours() -> None:
    assert _human_elapsed(3665) == "1h 1m 5s"


def test_human_elapsed_zero() -> None:
    assert _human_elapsed(0) == "—"


def test_human_size_bytes() -> None:
    assert _human_size(500) == "500 B"


def test_human_size_kb() -> None:
    assert _human_size(2048) == "2 KB"


def test_human_size_mb() -> None:
    assert _human_size(1_500_000) == "1.4 MB"


def test_human_size_zero() -> None:
    assert _human_size(0) == "—"


def test_parse_pipeline_start() -> None:
    result = _parse_pipeline_start("pipeline-2026-03-31-084018")
    assert result == datetime(2026, 3, 31, 8, 40, 18, tzinfo=UTC)


def test_parse_pipeline_start_invalid() -> None:
    assert _parse_pipeline_start("something-else") is None


# ---------------------------------------------------------------------------
# _next_free_id
# ---------------------------------------------------------------------------


def test_next_free_id_empty() -> None:
    assert _next_free_id([]) == 1


def test_next_free_id_sequential() -> None:
    entries = [
        DigestIndexEntry(
            digest_id=1, pipeline_dir_name="p1", run_date="2026-03-01", article_count=10
        ),
        DigestIndexEntry(
            digest_id=2, pipeline_dir_name="p2", run_date="2026-03-02", article_count=20
        ),
    ]
    assert _next_free_id(entries) == 3


def test_next_free_id_with_gap() -> None:
    entries = [
        DigestIndexEntry(
            digest_id=2, pipeline_dir_name="p2", run_date="2026-03-02", article_count=20
        ),
        DigestIndexEntry(
            digest_id=3, pipeline_dir_name="p3", run_date="2026-03-03", article_count=30
        ),
    ]
    assert _next_free_id(entries) == 1


# ---------------------------------------------------------------------------
# register_digest / unregister_digest
# ---------------------------------------------------------------------------


def test_register_digest_creates_index(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(
        pdir,
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    register_digest(tmp_path, pdir, digest)
    entries = _load_digest_index(tmp_path)
    assert len(entries) == 1
    assert entries[0].digest_id == 1
    assert entries[0].pipeline_dir_name == "pipeline-2026-03-01-100000"
    assert entries[0].article_count == 1


def test_register_digest_skips_failed(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(pdir, "2026-03-01", status="failed", completed_phases=["classify"])
    register_digest(tmp_path, pdir, digest)
    assert _load_digest_index(tmp_path) == []


def test_register_digest_skips_incomplete_phases(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(
        pdir,
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "enrich"],
    )
    register_digest(tmp_path, pdir, digest)
    assert _load_digest_index(tmp_path) == []


def test_register_digest_idempotent(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(
        pdir,
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
    )
    register_digest(tmp_path, pdir, digest)
    register_digest(tmp_path, pdir, digest)
    entries = _load_digest_index(tmp_path)
    assert len(entries) == 1


def test_register_digest_reuses_freed_id(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    _make_and_register(tmp_path, "pipeline-2026-03-02-100000", "2026-03-02")
    unregister_digest(tmp_path, 1)
    _make_and_register(tmp_path, "pipeline-2026-03-03-100000", "2026-03-03")
    entries = _load_digest_index(tmp_path)
    ids = {e.digest_id for e in entries}
    assert ids == {1, 2}


def test_register_digest_aggregates_usage(tmp_path: Path) -> None:
    import json

    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(
        pdir,
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    task1_meta = pdir / "classify-1" / "meta"
    task1_meta.mkdir(parents=True)
    (task1_meta / "usage.json").write_text(
        json.dumps({"elapsed_seconds": 10.5, "total_tokens": 500, "backend": "cli"})
    )
    task1_input = pdir / "classify-1" / "input"
    task1_input.mkdir(parents=True)
    (task1_input / "task_prompt.txt").write_text("A" * 1000)
    task1_output = pdir / "classify-1" / "output"
    task1_output.mkdir(parents=True)
    (task1_output / "agent_stdout.log").write_text("B" * 400)

    task2_meta = pdir / "classify-2" / "meta"
    task2_meta.mkdir(parents=True)
    (task2_meta / "usage.json").write_text(
        json.dumps({"elapsed_seconds": 5.0, "total_tokens": 300, "backend": "cli"})
    )
    task2_input = pdir / "classify-2" / "input"
    task2_input.mkdir(parents=True)
    (task2_input / "task_prompt.txt").write_text("C" * 500)
    task2_output = pdir / "classify-2" / "output"
    task2_output.mkdir(parents=True)
    (task2_output / "agent_stdout.log").write_text("D" * 200)

    register_digest(tmp_path, pdir, digest)
    entries = _load_digest_index(tmp_path)
    assert entries[0].elapsed_seconds == 15.5
    assert entries[0].total_tokens == 800
    assert entries[0].prompt_bytes == 1500
    assert entries[0].output_bytes == 600


def test_unregister_digest_returns_dir_name(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    result = unregister_digest(tmp_path, 1)
    assert result == "pipeline-2026-03-01-100000"
    assert _load_digest_index(tmp_path) == []


def test_unregister_digest_not_found(tmp_path: Path) -> None:
    assert unregister_digest(tmp_path, 99) is None


# ---------------------------------------------------------------------------
# _list_completed_digests
# ---------------------------------------------------------------------------


def test_list_empty_workdir(tmp_path: Path) -> None:
    assert _list_completed_digests(tmp_path / "nonexistent") == []


def test_list_returns_completed_digests(tmp_path: Path) -> None:
    _make_and_register(
        tmp_path,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[
            _article("2026-02-28T20:00:00+00:00"),
            _article("2026-03-01T10:00:00+00:00"),
        ],
    )
    result = _list_completed_digests(tmp_path)
    assert len(result) == 1
    s = result[0]
    assert s.digest_id == 1
    assert s.run_date == date(2026, 3, 1)
    assert s.article_count == 2
    assert s.coverage_end == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    assert s.pipeline_dir_name == "pipeline-2026-03-01-100000"
    assert s.started_at == datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)


def test_list_newest_first(tmp_path: Path) -> None:
    _make_and_register(
        tmp_path,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    _make_and_register(
        tmp_path,
        "pipeline-2026-03-02-100000",
        "2026-03-02",
        articles=[_article("2026-03-02T10:00:00+00:00")],
    )
    result = _list_completed_digests(tmp_path)
    assert len(result) == 2
    assert result[0].run_date == date(2026, 3, 2)
    assert result[1].run_date == date(2026, 3, 1)


def test_list_zero_article_digest(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01", articles=[])
    result = _list_completed_digests(tmp_path)
    assert len(result) == 1
    assert result[0].article_count == 0
    assert result[0].coverage_start is None
    assert result[0].coverage_end is None


# ---------------------------------------------------------------------------
# _find_digest_pipeline_dir / _find_latest_digest_pipeline_dir
# ---------------------------------------------------------------------------


def test_find_digest_by_id(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    _make_and_register(tmp_path, "pipeline-2026-03-02-100000", "2026-03-02")
    assert _find_digest_pipeline_dir(tmp_path, 1) == tmp_path / "pipeline-2026-03-01-100000"
    assert _find_digest_pipeline_dir(tmp_path, 2) == tmp_path / "pipeline-2026-03-02-100000"
    assert _find_digest_pipeline_dir(tmp_path, 99) is None


def test_find_latest_digest(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    _make_and_register(tmp_path, "pipeline-2026-03-02-100000", "2026-03-02")
    result = _find_latest_digest_pipeline_dir(tmp_path)
    assert result == tmp_path / "pipeline-2026-03-02-100000"


def test_find_latest_digest_empty(tmp_path: Path) -> None:
    assert _find_latest_digest_pipeline_dir(tmp_path) is None


# ---------------------------------------------------------------------------
# DigestInfoController.digest_info
# ---------------------------------------------------------------------------


def test_digest_info_empty_workdir(tmp_path: Path, capsys: object) -> None:
    settings = MagicMock()
    settings.orchestrator.workdir_root = tmp_path / "nonexistent"
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "no digests found" in out.lower()


def test_digest_info_shows_digests_and_gap(tmp_path: Path, capsys: object) -> None:
    workdir = tmp_path / "workdirs"
    coverage_end_1 = "2026-02-28T12:15:00+00:00"
    coverage_start_2 = "2026-02-28T20:12:00+00:00"
    _make_and_register(
        workdir,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[
            _article("2026-02-27T06:00:00+00:00"),
            _article(coverage_end_1),
        ],
        coverage_start="2026-02-27T00:00:00+00:00",
    )
    _make_and_register(
        workdir,
        "pipeline-2026-03-02-100000",
        "2026-03-02",
        articles=[
            _article(coverage_start_2),
            _article("2026-03-01T14:30:00+00:00"),
        ],
        coverage_start=coverage_start_2,
    )

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]

    assert "2026-03-02" in out
    assert "2026-03-01" in out
    assert "Uncovered periods" in out
    assert _local_str(coverage_end_1) in out
    assert _local_str(coverage_start_2) in out


def test_digest_info_no_gap_when_overlapping(tmp_path: Path, capsys: object) -> None:
    workdir = tmp_path / "workdirs"
    _make_and_register(
        workdir,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[
            _article("2026-02-27T06:00:00+00:00"),
            _article("2026-02-28T20:00:00+00:00"),
        ],
        coverage_start="2026-02-27T00:00:00+00:00",
    )
    _make_and_register(
        workdir,
        "pipeline-2026-03-02-100000",
        "2026-03-02",
        articles=[
            _article("2026-02-28T08:00:00+00:00"),
            _article("2026-03-01T14:30:00+00:00"),
        ],
        coverage_start="2026-02-28T20:00:00+00:00",
    )

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]

    assert "Uncovered periods" not in out


def test_digest_info_zero_article_excluded_from_gaps(tmp_path: Path, capsys: object) -> None:
    workdir = tmp_path / "workdirs"
    coverage_end_1 = "2026-02-28T12:00:00+00:00"
    coverage_start_3 = "2026-03-03T08:00:00+00:00"
    _make_and_register(
        workdir,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article(coverage_end_1)],
        coverage_start="2026-02-28T00:00:00+00:00",
    )
    _make_and_register(workdir, "pipeline-2026-03-02-100000", "2026-03-02", articles=[])
    _make_and_register(
        workdir,
        "pipeline-2026-03-03-100000",
        "2026-03-03",
        articles=[_article(coverage_start_3)],
        coverage_start=coverage_start_3,
    )

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]

    assert "Uncovered periods" in out
    assert _local_str(coverage_end_1) in out
    assert _local_str(coverage_start_3) in out


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


def test_gc_old_pipelines_cleans_index(tmp_path: Path) -> None:
    today = date.today()
    old_date = today - timedelta(days=10)
    recent_date = today - timedelta(days=1)

    _make_and_register(
        tmp_path,
        f"pipeline-{old_date.isoformat()}-100000",
        old_date.isoformat(),
    )
    _make_and_register(
        tmp_path,
        f"pipeline-{recent_date.isoformat()}-100000",
        recent_date.isoformat(),
    )
    assert len(_load_digest_index(tmp_path)) == 2

    gc_old_pipelines(tmp_path, keep_days=7)

    entries = _load_digest_index(tmp_path)
    assert len(entries) == 1
    assert recent_date.isoformat() in entries[0].pipeline_dir_name


def test_gc_old_pipelines_noop_when_missing(tmp_path: Path) -> None:
    assert gc_old_pipelines(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_digest_cli_help() -> None:
    from click.testing import CliRunner

    from news_recap.main import news_recap

    runner = CliRunner()
    result = runner.invoke(news_recap, ["list", "--help"])
    assert result.exit_code == 0
    assert "completed digests" in result.output.lower()


def test_delete_cli_help() -> None:
    from click.testing import CliRunner

    from news_recap.main import news_recap

    runner = CliRunner()
    result = runner.invoke(news_recap, ["delete", "--help"])
    assert result.exit_code == 0
    assert "digest_id" in result.output.lower()


def test_delete_nonexistent_digest(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.orchestrator.workdir_root = tmp_path / "nonexistent"
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().delete_digest(99)
    assert any("not found" in l.lower() for l in lines)


def test_delete_removes_pipeline_dir_and_index_entry(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    pdir = workdir / "pipeline-2026-03-01-100000"
    _make_and_register(
        workdir,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    assert pdir.exists()
    assert len(_load_digest_index(workdir)) == 1

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().delete_digest(1)

    assert not pdir.exists()
    assert _load_digest_index(workdir) == []
    assert any("deleted" in l.lower() for l in lines)
    assert any("available" in l.lower() for l in lines)
