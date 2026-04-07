"""Tests for digest index, _list_digests, and DigestInfoController."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec

from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.digest_info import (
    DigestInfoController,
    _find_uncovered_periods,
    _human_elapsed,
    _human_size,
    _last_successful_ingestion,
    _smart_period,
)
from news_recap.recap.models import Digest, DigestArticle
from news_recap.recap.pipeline_setup import (
    DigestIndexEntry,
    _find_digest_pipeline_dir,
    _find_latest_digest_pipeline_dir,
    _list_digests,
    _load_digest_index,
    _next_free_id,
    _parse_pipeline_start,
    create_digest_entry,
    ensure_digest_entry,
    finalize_digest_entry,
    gc_old_pipelines,
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
    """Create a completed digest on disk, allocate an ID and finalize it."""
    pdir = workdir / dir_name
    digest = _make_digest(
        pdir,
        run_date,
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=articles,
        coverage_start=coverage_start,
    )
    create_digest_entry(
        workdir, dir_name, run_date, len(articles or []), coverage_start=coverage_start
    )
    finalize_digest_entry(workdir, pdir, digest)
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
    """Format a UTC ISO timestamp as local ``YYYY-MM-DD HH:MM:SS``."""
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_smart_period_same_day() -> None:
    e = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    l = datetime(2026, 3, 1, 8, 30, tzinfo=UTC)
    el = e.astimezone()
    ll = l.astimezone()
    result = _smart_period(e, l)
    assert el.strftime("%H:%M:%S") in result
    assert ll.strftime("%H:%M:%S") in result
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
# Backward compatibility — legacy index without status field
# ---------------------------------------------------------------------------


def test_legacy_index_without_status_defaults_to_completed(tmp_path: Path) -> None:
    """An existing digests.json without a ``status`` field should default to 'completed'."""
    import json

    legacy_entry = {
        "digest_id": 1,
        "pipeline_dir_name": "pipeline-2026-03-01-100000",
        "run_date": "2026-03-01",
        "article_count": 10,
    }
    (tmp_path / "digests.json").write_text(json.dumps([legacy_entry]))
    entries = _load_digest_index(tmp_path)
    assert len(entries) == 1
    assert entries[0].status == "completed"

    summaries = _list_digests(tmp_path)
    assert len(summaries) == 1
    assert summaries[0].status == "completed"


# ---------------------------------------------------------------------------
# create_digest_entry / finalize_digest_entry / unregister_digest
# ---------------------------------------------------------------------------


def test_create_digest_entry_assigns_id(tmp_path: Path) -> None:
    digest_id = create_digest_entry(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01", 5)
    assert digest_id == 1
    entries = _load_digest_index(tmp_path)
    assert len(entries) == 1
    assert entries[0].status == "running"
    assert entries[0].article_count == 5


def test_create_digest_entry_increments_ids(tmp_path: Path) -> None:
    id1 = create_digest_entry(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01", 5)
    id2 = create_digest_entry(tmp_path, "pipeline-2026-03-02-100000", "2026-03-02", 10)
    assert id1 == 1
    assert id2 == 2


def test_create_digest_entry_reuses_freed_id(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    _make_and_register(tmp_path, "pipeline-2026-03-02-100000", "2026-03-02")
    unregister_digest(tmp_path, 1)
    _make_and_register(tmp_path, "pipeline-2026-03-03-100000", "2026-03-03")
    entries = _load_digest_index(tmp_path)
    ids = {e.digest_id for e in entries}
    assert ids == {1, 2}


def test_finalize_digest_entry_updates_status(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(
        pdir,
        "2026-03-01",
        status="completed",
        completed_phases=["classify", "oneshot_digest"],
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    create_digest_entry(tmp_path, pdir.name, "2026-03-01", 1)
    finalize_digest_entry(tmp_path, pdir, digest)
    entries = _load_digest_index(tmp_path)
    assert entries[0].status == "completed"
    assert entries[0].article_count == 1


def test_finalize_failed_digest(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(pdir, "2026-03-01", status="failed", completed_phases=["classify"])
    create_digest_entry(tmp_path, pdir.name, "2026-03-01", 5)
    finalize_digest_entry(tmp_path, pdir, digest)
    entries = _load_digest_index(tmp_path)
    assert entries[0].status == "failed"


def test_finalize_aggregates_usage(tmp_path: Path) -> None:
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

    create_digest_entry(tmp_path, pdir.name, "2026-03-01", 1)
    finalize_digest_entry(tmp_path, pdir, digest)
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
# ensure_digest_entry
# ---------------------------------------------------------------------------


def test_ensure_digest_entry_creates_for_legacy(tmp_path: Path) -> None:
    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(pdir, "2026-03-01", status="running", completed_phases=["classify"])
    assert _load_digest_index(tmp_path) == []
    ensure_digest_entry(tmp_path, pdir, digest)
    entries = _load_digest_index(tmp_path)
    assert len(entries) == 1
    assert entries[0].status == "running"


def test_ensure_digest_entry_noop_when_exists(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    entries_before = _load_digest_index(tmp_path)
    assert len(entries_before) == 1

    pdir = tmp_path / "pipeline-2026-03-01-100000"
    digest = _make_digest(pdir, "2026-03-01", status="running", completed_phases=["classify"])
    ensure_digest_entry(tmp_path, pdir, digest)
    entries_after = _load_digest_index(tmp_path)
    assert len(entries_after) == 1
    assert entries_after[0].status == entries_before[0].status


# ---------------------------------------------------------------------------
# _find_latest_digest_pipeline_dir — status filtering
# ---------------------------------------------------------------------------


def test_find_latest_digest_skips_non_completed(tmp_path: Path) -> None:
    _make_and_register(
        tmp_path,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    pdir2 = tmp_path / "pipeline-2026-03-02-100000"
    _make_digest(pdir2, "2026-03-02", status="running")
    create_digest_entry(tmp_path, pdir2.name, "2026-03-02", 5)
    result = _find_latest_digest_pipeline_dir(tmp_path)
    assert result == tmp_path / "pipeline-2026-03-01-100000"


# ---------------------------------------------------------------------------
# _list_digests
# ---------------------------------------------------------------------------


def test_list_empty_workdir(tmp_path: Path) -> None:
    assert _list_digests(tmp_path / "nonexistent") == []


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
    result = _list_digests(tmp_path)
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
    result = _list_digests(tmp_path)
    assert len(result) == 2
    assert result[0].run_date == date(2026, 3, 2)
    assert result[1].run_date == date(2026, 3, 1)


def test_list_zero_article_digest(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01", articles=[])
    result = _list_digests(tmp_path)
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
    settings.data_dir = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "no digests found" in out.lower()


def test_digest_info_hides_gap_with_zero_articles(tmp_path: Path, capsys: object) -> None:
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
    settings.data_dir = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]

    assert "2026-03-02" in out
    assert "2026-03-01" in out

    summaries = _list_digests(workdir)
    gaps = _find_uncovered_periods(summaries)
    assert len(gaps) == 1
    assert gaps[0] == (
        datetime.fromisoformat(coverage_end_1),
        datetime.fromisoformat(coverage_start_2),
    )
    assert "Uncovered periods" not in out


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
    settings.data_dir = tmp_path
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
    settings.data_dir = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]

    summaries = _list_digests(workdir)
    gaps = _find_uncovered_periods(summaries)
    assert len(gaps) == 1
    assert gaps[0] == (
        datetime.fromisoformat(coverage_end_1),
        datetime.fromisoformat(coverage_start_3),
    )
    assert "Uncovered periods" not in out


# ---------------------------------------------------------------------------
# _last_successful_ingestion
# ---------------------------------------------------------------------------


def _store_with_runs(tmp_path: Path, statuses: list[tuple[str, datetime | None]]) -> IngestionStore:
    """Create an IngestionStore and register runs with given (status, finished_at) pairs."""
    from news_recap.ingestion.models import IngestionRunCounters, RunStatus

    store = IngestionStore(tmp_path)
    for status_str, finished_at in statuses:
        run_id = store.start_run(source="rss")
        store.finish_run(run_id, status=RunStatus(status_str), counters=IngestionRunCounters())
        if finished_at is not None:
            runs = store._load_runs()  # noqa: SLF001
            for r in runs.runs:
                if r.run_id == run_id:
                    r.finished_at = finished_at
            store._save_runs()  # noqa: SLF001
    return store


def test_last_successful_ingestion_returns_finished_at(tmp_path: Path) -> None:
    finished = datetime(2026, 4, 5, 10, 0, 0, tzinfo=UTC)
    store = _store_with_runs(tmp_path, [("succeeded", finished)])
    assert _last_successful_ingestion(store) == finished


def test_last_successful_ingestion_skips_failed(tmp_path: Path) -> None:
    good_time = datetime(2026, 4, 4, 8, 0, tzinfo=UTC)
    store = _store_with_runs(tmp_path, [("failed", None), ("succeeded", good_time)])
    assert _last_successful_ingestion(store) == good_time


def test_last_successful_ingestion_no_runs(tmp_path: Path) -> None:
    store = IngestionStore(tmp_path)
    assert _last_successful_ingestion(store) is None


# ---------------------------------------------------------------------------
# _find_uncovered_periods — trailing gap
# ---------------------------------------------------------------------------


def test_trailing_gap_shown_when_latest_ingested_after_coverage(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    _make_and_register(
        workdir,
        "pipeline-2026-04-01-100000",
        "2026-04-01",
        articles=[_article("2026-04-01T12:00:00+00:00")],
        coverage_start="2026-04-01T00:00:00+00:00",
    )
    summaries = _list_digests(workdir)
    latest_ingested = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)
    gaps = _find_uncovered_periods(summaries, latest_ingested=latest_ingested)
    assert len(gaps) == 1
    assert gaps[0] == (
        datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
    )


def test_no_trailing_gap_when_no_latest_ingested(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    _make_and_register(
        workdir,
        "pipeline-2026-04-01-100000",
        "2026-04-01",
        articles=[_article("2026-04-01T12:00:00+00:00")],
        coverage_start="2026-04-01T00:00:00+00:00",
    )
    summaries = _list_digests(workdir)
    gaps = _find_uncovered_periods(summaries)
    assert gaps == []


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


def test_delete_running_digest_by_id(tmp_path: Path) -> None:
    workdir = tmp_path / "workdirs"
    pdir = workdir / "pipeline-2026-03-02-100000"
    _make_digest(pdir, "2026-03-02", status="running", completed_phases=["classify"])
    create_digest_entry(workdir, pdir.name, "2026-03-02", 5)
    assert pdir.exists()

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        lines = DigestInfoController().delete_digest(1)
    assert not pdir.exists()
    assert any("deleted" in l.lower() for l in lines)
    assert not any("available" in l.lower() for l in lines)


# ---------------------------------------------------------------------------
# _list_digests
# ---------------------------------------------------------------------------


def test_list_all_includes_running_and_completed(tmp_path: Path) -> None:
    _make_and_register(
        tmp_path,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    pdir2 = tmp_path / "pipeline-2026-03-02-100000"
    _make_digest(pdir2, "2026-03-02", status="running", completed_phases=["classify"])
    create_digest_entry(tmp_path, pdir2.name, "2026-03-02", 5)
    result = _list_digests(tmp_path, completed_only=False)
    assert len(result) == 2
    statuses = {s.status for s in result}
    assert statuses == {"completed", "running"}


def test_list_all_sorted_newest_first(tmp_path: Path) -> None:
    for d in ("01", "03", "02"):
        name = f"pipeline-2026-03-{d}-100000"
        pdir = tmp_path / name
        _make_digest(pdir, f"2026-03-{d}", status="failed")
        create_digest_entry(tmp_path, name, f"2026-03-{d}", 0)
    result = _list_digests(tmp_path, completed_only=False)
    assert [r.pipeline_dir_name for r in result] == [
        "pipeline-2026-03-03-100000",
        "pipeline-2026-03-02-100000",
        "pipeline-2026-03-01-100000",
    ]


def test_list_completed_excludes_running(tmp_path: Path) -> None:
    _make_and_register(tmp_path, "pipeline-2026-03-01-100000", "2026-03-01")
    pdir2 = tmp_path / "pipeline-2026-03-02-100000"
    _make_digest(pdir2, "2026-03-02", status="running")
    create_digest_entry(tmp_path, pdir2.name, "2026-03-02", 5)
    result = _list_digests(tmp_path)
    assert len(result) == 1
    assert result[0].status == "completed"


# ---------------------------------------------------------------------------
# list --all (CLI)
# ---------------------------------------------------------------------------


def test_list_all_shows_running_and_failed(tmp_path: Path, capsys: object) -> None:
    workdir = tmp_path / "workdirs"
    _make_and_register(
        workdir,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    pdir2 = workdir / "pipeline-2026-03-02-100000"
    _make_digest(pdir2, "2026-03-02", status="failed", completed_phases=["classify"])
    create_digest_entry(workdir, pdir2.name, "2026-03-02", 5)
    digest2 = Digest(
        digest_id="d-2",
        run_date="2026-03-02",
        status="failed",
        pipeline_dir=str(pdir2),
        articles=[],
        completed_phases=["classify"],
    )
    finalize_digest_entry(workdir, pdir2, digest2)

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    settings.data_dir = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info(show_all=True)
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "failed" in out.lower()
    assert "Status" in out


def test_list_default_hides_non_completed(tmp_path: Path, capsys: object) -> None:
    workdir = tmp_path / "workdirs"
    _make_and_register(
        workdir,
        "pipeline-2026-03-01-100000",
        "2026-03-01",
        articles=[_article("2026-03-01T10:00:00+00:00")],
    )
    pdir2 = workdir / "pipeline-2026-03-02-100000"
    _make_digest(pdir2, "2026-03-02", status="failed", completed_phases=["classify"])
    create_digest_entry(workdir, pdir2.name, "2026-03-02", 5)
    digest2 = Digest(
        digest_id="d-2",
        run_date="2026-03-02",
        status="failed",
        pipeline_dir=str(pdir2),
        articles=[],
        completed_phases=["classify"],
    )
    finalize_digest_entry(workdir, pdir2, digest2)

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    settings.data_dir = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info()
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "Status" not in out


def test_list_all_with_no_completed_digests(tmp_path: Path, capsys: object) -> None:
    workdir = tmp_path / "workdirs"
    pdir = workdir / "pipeline-2026-03-02-100000"
    _make_digest(pdir, "2026-03-02", status="running", completed_phases=["classify"])
    create_digest_entry(workdir, pdir.name, "2026-03-02", 5)

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir
    settings.data_dir = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        DigestInfoController().digest_info(show_all=True)
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "running" in out.lower()
