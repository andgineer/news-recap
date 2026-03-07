"""Tests for the Phase 1 digest web viewer."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from news_recap.main import news_recap
from news_recap.recap.models import Digest, DigestArticle, DigestBlock, DigestSection
from news_recap.storage.io import save_msgspec
from news_recap.web.server import create_app, find_latest_digest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_digest(
    pipeline_dir: Path,
    *,
    status: str = "completed",
    date_str: str = "2026-03-06",
    digest_id: str = "test-digest-id",
) -> Digest:
    article = DigestArticle(
        article_id="art-1",
        title="Original title",
        url="https://example.com/1",
        source="Example",
        published_at="2026-03-06T10:00:00",
        clean_text="some text",
        enriched_title="Enriched title",
    )
    block = DigestBlock(title="Block summary", article_ids=["art-1"])
    section = DigestSection(title="Top Stories", block_indices=[0])
    return Digest(
        digest_id=digest_id,
        business_date=date_str,
        status=status,
        pipeline_dir=str(pipeline_dir),
        articles=[article],
        blocks=[block],
        recaps=[section],
        day_summary="Great day summary.",
    )


def _write_digest(pipeline_dir: Path, digest: Digest) -> Path:
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    path = pipeline_dir / "digest.json"
    save_msgspec(path, digest)
    return path


# ---------------------------------------------------------------------------
# find_latest_digest
# ---------------------------------------------------------------------------


def test_find_latest_digest_returns_completed(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"
    digest = _make_digest(pipeline_dir)
    _write_digest(pipeline_dir, digest)

    result = find_latest_digest(workdir, "2026-03-06")
    assert result is not None
    found_digest, found_path = result
    assert found_digest.digest_id == "test-digest-id"
    assert found_path == pipeline_dir / "digest.json"


def test_find_latest_digest_skips_non_completed(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"
    digest = _make_digest(pipeline_dir, status="in_progress")
    _write_digest(pipeline_dir, digest)

    result = find_latest_digest(workdir, "2026-03-06")
    assert result is None


def test_find_latest_digest_returns_none_for_missing_date(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    result = find_latest_digest(workdir, "2099-01-01")
    assert result is None


def test_find_latest_digest_picks_latest_by_dir_name(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    old_dir = workdir / "pipeline-2026-03-06-090000"
    new_dir = workdir / "pipeline-2026-03-06-180000"

    old_digest = _make_digest(old_dir, digest_id="old-id")
    new_digest = _make_digest(new_dir, digest_id="new-id")
    _write_digest(old_dir, old_digest)
    _write_digest(new_dir, new_digest)

    result = find_latest_digest(workdir, "2026-03-06")
    assert result is not None
    found_digest, _ = result
    assert found_digest.digest_id == "new-id"


# ---------------------------------------------------------------------------
# Flask routes — happy path
# ---------------------------------------------------------------------------


def test_digest_page_renders_completed_digest(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"
    digest = _make_digest(pipeline_dir)
    _write_digest(pipeline_dir, digest)

    app = create_app(workdir)
    client = app.test_client()

    resp = client.get("/digest/2026-03-06")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "2026-03-06" in body
    assert "Great day summary." in body
    assert "Top Stories" in body
    assert "Block summary" in body
    assert "Enriched title" in body
    assert "https://example.com/1" in body


def test_root_redirects_to_pinned_date(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    app = create_app(workdir, pinned_date="2026-03-06")
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 302
    assert "/digest/2026-03-06" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Flask routes — error cases
# ---------------------------------------------------------------------------


def test_digest_page_returns_404_for_missing_digest(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    app = create_app(workdir)
    client = app.test_client()

    resp = client.get("/digest/2026-03-06")
    assert resp.status_code == 404


def test_digest_page_returns_400_for_invalid_date(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    app = create_app(workdir)
    client = app.test_client()

    resp = client.get("/digest/not-a-date")
    assert resp.status_code == 400


def test_digest_page_skips_incomplete_digest(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"
    digest = _make_digest(pipeline_dir, status="failed")
    _write_digest(pipeline_dir, digest)

    app = create_app(workdir)
    client = app.test_client()

    resp = client.get("/digest/2026-03-06")
    assert resp.status_code == 404


def test_digest_page_missing_article_reference_silently_skipped(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"

    # Block references an article that doesn't exist in articles list
    block = DigestBlock(title="Orphan block", article_ids=["nonexistent-art"])
    section = DigestSection(title="Section", block_indices=[0])
    digest = Digest(
        digest_id="orphan-digest",
        business_date="2026-03-06",
        status="completed",
        pipeline_dir=str(pipeline_dir),
        articles=[],
        blocks=[block],
        recaps=[section],
    )
    _write_digest(pipeline_dir, digest)

    app = create_app(workdir)
    client = app.test_client()

    # Must not raise 500
    resp = client.get("/digest/2026-03-06")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _safe_index — path traversal rejection
# ---------------------------------------------------------------------------


def test_safe_index_uses_ondisk_path_not_pipeline_dir_metadata(tmp_path: Path) -> None:
    """Index uses the actual on-disk path, so stale/malformed pipeline_dir is ignored."""
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"

    # pipeline_dir metadata points somewhere else entirely (stale, wrong, tampered)
    stale_dir = tmp_path / "some-other-location"
    digest = Digest(
        digest_id="stale-meta-id",
        business_date="2026-03-06",
        status="completed",
        pipeline_dir=str(stale_dir),  # does not match actual file location
        articles=[],
        blocks=[DigestBlock(title="Block", article_ids=[])],
    )
    _write_digest(pipeline_dir, digest)

    app = create_app(workdir)
    client = app.test_client()

    # Page must render (digest is found via glob, not pipeline_dir)
    resp = client.get("/digest/2026-03-06")
    assert resp.status_code == 200

    # API must resolve via index populated from the real on-disk path
    api_resp = client.get("/api/digest/stale-meta-id/block/0/summary")
    assert api_resp.status_code == 501  # found (Phase 2 not implemented), not 404


def test_safe_index_rejects_path_outside_workdir_root(tmp_path: Path) -> None:
    """_safe_index must not index a path that resolves outside workdir_root."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    outside_path = tmp_path / "outside" / "digest.json"
    outside_path.parent.mkdir()

    # Write a valid digest outside workdir so we can call _safe_index with it
    digest = Digest(
        digest_id="outside-id",
        business_date="2026-03-06",
        status="completed",
        pipeline_dir=str(outside_path.parent),
        articles=[],
    )
    save_msgspec(outside_path, digest)

    # create_app startup glob only covers workdir_root, so this digest won't be picked up
    app = create_app(workdir)
    client = app.test_client()

    # Must be 404 — digest was never indexed
    api_resp = client.get("/api/digest/outside-id/block/0/summary")
    assert api_resp.status_code == 404


# ---------------------------------------------------------------------------
# Startup indexing
# ---------------------------------------------------------------------------


def test_startup_index_populated_without_page_load(tmp_path: Path) -> None:
    """Digest placed on disk before create_app must be findable by digest_id."""
    workdir = tmp_path / "workdir"
    pipeline_dir = workdir / "pipeline-2026-03-06-120000"
    digest = _make_digest(pipeline_dir, digest_id="startup-digest-id")
    _write_digest(pipeline_dir, digest)

    app = create_app(workdir)
    client = app.test_client()

    # Do NOT hit /digest/<date> first — assert the startup glob populated the index
    resp = client.get("/api/digest/startup-digest-id/block/0/summary")
    # 501 means the route resolved the digest (Phase 2 not implemented), not 404
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_serve_help() -> None:
    runner = CliRunner()
    result = runner.invoke(news_recap, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--date" in result.output
    assert "--host" in result.output
    assert "--port" in result.output
