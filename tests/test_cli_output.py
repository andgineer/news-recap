"""Tests for CLI output formatting: _collect_task_rows, _print_digest_detail,
_print_ingest, _print_schedule, _emit_prompt, _emit_run_summary, and info <digest_id>.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import allure
import msgspec
from click.testing import CliRunner

from news_recap.main import (
    _collect_task_rows,
    _emit_pipeline,
    _emit_prompt,
    news_recap,
)
from news_recap.recap.digest_info import DigestInfoController, DigestSummary
from news_recap.recap.launcher import _emit_run_summary
from news_recap.recap.models import Digest, DigestArticle

pytestmark = [
    allure.epic("CLI"),
    allure.feature("Output Formatting"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(
    article_id: str = "a1", published_at: str = "2026-03-01T10:00:00+00:00"
) -> DigestArticle:
    return DigestArticle(
        article_id=article_id,
        title=f"Title {article_id}",
        url=f"https://example.com/{article_id}",
        source="test",
        published_at=published_at,
        clean_text="body",
    )


def _make_task_dir(
    workdir: Path,
    name: str,
    *,
    elapsed: float = 0.0,
    tokens: int = 0,
    prompt_text: str = "",
    output_text: str = "",
) -> Path:
    """Create a fake task directory with optional usage/input/output files."""
    task_dir = workdir / name
    task_dir.mkdir(parents=True, exist_ok=True)
    if elapsed or tokens:
        meta_dir = task_dir / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        usage = {"elapsed_seconds": elapsed}
        if tokens:
            usage["total_tokens"] = tokens
        (meta_dir / "usage.json").write_text(json.dumps(usage))
    if prompt_text:
        input_dir = task_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / "task_prompt.txt").write_text(prompt_text)
    if output_text:
        output_dir = task_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "agent_stdout.log").write_text(output_text)
    return task_dir


def _make_digest_on_disk(
    pipeline_dir: Path,
    *,
    status: str = "completed",
    n_articles: int = 3,
) -> Digest:
    articles = [_article(f"art-{i}") for i in range(n_articles)]
    digest = Digest(
        digest_id="test-digest",
        run_date="2026-03-01",
        status=status,
        pipeline_dir=str(pipeline_dir),
        articles=articles,
        completed_phases=["classify", "oneshot_digest"],
    )
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "digest.json").write_bytes(msgspec.json.encode(digest))
    return digest


def _make_summary(
    *,
    digest_id: int = 1,
    pipeline_dir_name: str = "pipeline-2026-03-01-100000",
    elapsed: float = 125.0,
    tokens: int = 5000,
    prompt_bytes: int = 2048,
    output_bytes: int = 1024,
) -> DigestSummary:
    return DigestSummary(
        digest_id=digest_id,
        run_date=date(2026, 3, 1),
        article_count=5,
        coverage_start=datetime(2026, 2, 28, 20, 0, tzinfo=UTC),
        coverage_end=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        pipeline_dir_name=pipeline_dir_name,
        started_at=datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
        elapsed_seconds=elapsed,
        total_tokens=tokens,
        prompt_bytes=prompt_bytes,
        output_bytes=output_bytes,
    )


# ---------------------------------------------------------------------------
# _collect_task_rows
# ---------------------------------------------------------------------------


def test_collect_task_rows_empty_dir(tmp_path: Path) -> None:
    assert _collect_task_rows(tmp_path) == []


def test_collect_task_rows_skips_files(tmp_path: Path) -> None:
    (tmp_path / "not-a-dir.txt").write_text("hello")
    assert _collect_task_rows(tmp_path) == []


def test_collect_task_rows_skips_empty_task_dir(tmp_path: Path) -> None:
    (tmp_path / "classify-1").mkdir()
    assert _collect_task_rows(tmp_path) == []


def test_collect_task_rows_reads_usage(tmp_path: Path) -> None:
    _make_task_dir(tmp_path, "classify-1", elapsed=10.5, tokens=500)
    rows = _collect_task_rows(tmp_path)
    assert len(rows) == 1
    name, elapsed, prompt_sz, output_sz, tok = rows[0]
    assert name == "classify-1"
    assert elapsed == 10.5
    assert tok == 500
    assert prompt_sz == 0
    assert output_sz == 0


def test_collect_task_rows_reads_file_sizes(tmp_path: Path) -> None:
    _make_task_dir(
        tmp_path,
        "enrich-1",
        prompt_text="A" * 1000,
        output_text="B" * 400,
    )
    rows = _collect_task_rows(tmp_path)
    assert len(rows) == 1
    _, _, prompt_sz, output_sz, _ = rows[0]
    assert prompt_sz == 1000
    assert output_sz == 400


def test_collect_task_rows_multiple_sorted(tmp_path: Path) -> None:
    _make_task_dir(tmp_path, "enrich-1", elapsed=5.0)
    _make_task_dir(tmp_path, "classify-1", elapsed=10.0)
    rows = _collect_task_rows(tmp_path)
    assert len(rows) == 2
    assert rows[0][0] == "classify-1"
    assert rows[1][0] == "enrich-1"


def test_collect_task_rows_handles_tokens_used_fallback(tmp_path: Path) -> None:
    """When usage.json has ``tokens_used`` instead of ``total_tokens``."""
    task_dir = tmp_path / "map-1"
    task_dir.mkdir(parents=True)
    meta = task_dir / "meta"
    meta.mkdir()
    (meta / "usage.json").write_text(json.dumps({"elapsed_seconds": 3.0, "tokens_used": 200}))
    rows = _collect_task_rows(tmp_path)
    assert rows[0][4] == 200


def test_collect_task_rows_handles_corrupt_usage(tmp_path: Path) -> None:
    """Corrupt usage.json is silently ignored."""
    task_dir = tmp_path / "corrupt-1"
    task_dir.mkdir(parents=True)
    meta = task_dir / "meta"
    meta.mkdir()
    (meta / "usage.json").write_text("not json!!!")
    (task_dir / "input").mkdir()
    (task_dir / "input" / "task_prompt.txt").write_text("prompt")
    rows = _collect_task_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][0] == "corrupt-1"
    assert rows[0][1] == 0.0  # elapsed
    assert rows[0][4] == 0  # tokens


# ---------------------------------------------------------------------------
# info <digest_id> CLI
# ---------------------------------------------------------------------------


def test_info_digest_not_found() -> None:
    runner = CliRunner()
    with patch.object(DigestInfoController, "digest_detail", return_value=None):
        result = runner.invoke(news_recap, ["--no-color", "info", "99"])
    assert result.exit_code != 0
    assert "Digest #99 not found" in result.output


def test_info_digest_shows_detail(tmp_path: Path) -> None:
    summary = _make_summary(pipeline_dir_name="pipeline-2026-03-01-100000")
    settings = MagicMock()
    settings.orchestrator.workdir_root.resolve.return_value = tmp_path
    runner = CliRunner()
    with (
        patch.object(DigestInfoController, "digest_detail", return_value=summary),
        patch("news_recap.main.Settings.from_env", return_value=settings),
    ):
        result = runner.invoke(news_recap, ["--no-color", "info", "1"])
    assert result.exit_code == 0
    assert "Digest #1" in result.output
    assert "2026-03-01" in result.output
    assert "5" in result.output  # article_count
    assert "2m 5s" in result.output  # elapsed
    assert "2 KB" in result.output  # prompts
    assert "1 KB" in result.output  # output
    assert "5,000" in result.output  # tokens
    started_local = summary.started_at.astimezone()
    assert started_local.strftime("%Y-%m-%d %H:%M") in result.output


def test_info_digest_shows_task_table(tmp_path: Path) -> None:
    workdir = tmp_path / "pipeline-2026-03-01-100000"
    workdir.mkdir(parents=True)
    _make_task_dir(workdir, "classify-1", elapsed=10.0, tokens=300, prompt_text="A" * 500)
    _make_task_dir(workdir, "enrich-1", elapsed=5.0, tokens=200, output_text="B" * 300)

    summary = _make_summary(pipeline_dir_name="pipeline-2026-03-01-100000")
    settings = MagicMock()
    settings.orchestrator.workdir_root.resolve.return_value = tmp_path

    runner = CliRunner()
    with (
        patch.object(DigestInfoController, "digest_detail", return_value=summary),
        patch("news_recap.main.Settings.from_env", return_value=settings),
    ):
        result = runner.invoke(news_recap, ["--no-color", "info", "1"])
    assert result.exit_code == 0
    assert "classify-1" in result.output
    assert "enrich-1" in result.output
    assert "Phase" in result.output


def test_info_digest_no_task_table_when_no_workdir(tmp_path: Path) -> None:
    """When the workdir doesn't exist, only the summary is printed."""
    summary = _make_summary(pipeline_dir_name="nonexistent-dir")
    settings = MagicMock()
    settings.orchestrator.workdir_root.resolve.return_value = tmp_path

    runner = CliRunner()
    with (
        patch.object(DigestInfoController, "digest_detail", return_value=summary),
        patch("news_recap.main.Settings.from_env", return_value=settings),
    ):
        result = runner.invoke(news_recap, ["--no-color", "info", "1"])
    assert result.exit_code == 0
    assert "Digest #1" in result.output
    assert "Phase" not in result.output


def test_info_without_id_shows_app_paths() -> None:
    """``info`` without an argument still shows app paths."""
    runner = CliRunner()
    settings = MagicMock()
    settings.data_dir = Path("/tmp/data")
    settings.orchestrator.workdir_root = Path("/tmp/workdirs")
    with (
        patch("news_recap.main.Settings.from_env", return_value=settings),
        patch("news_recap.main._platform", return_value="linux"),
        patch("news_recap.main._app_dir", return_value=Path("/tmp/app")),
        patch("news_recap.main._log_dir", return_value=Path("/tmp/logs")),
    ):
        result = runner.invoke(news_recap, ["--no-color", "info"])
    assert result.exit_code == 0
    assert "Data" in result.output


# ---------------------------------------------------------------------------
# _print_ingest via CLI
# ---------------------------------------------------------------------------


def test_ingest_output_plain(tmp_path: Path, monkeypatch) -> None:
    """Structured plain ingestion output includes expected keywords."""
    from news_recap.ingestion.sources.rss import RssFetchResponse, RssSource

    data_dir = tmp_path / "ingest-test"
    monkeypatch.setenv("NEWS_RECAP_DEDUP_MODEL_NAME", "hashing-test")
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(data_dir))

    _RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>T1</title><link>https://example.com/1</link>
    <pubDate>Tue, 17 Feb 2026 13:18:07 +0000</pubDate><guid>g1</guid></item>
</channel></rss>"""

    def _request(self, url, *, etag=None, last_modified=None):
        return RssFetchResponse(
            raw_xml=_RSS_XML, etag='"e1"', last_modified="Tue, 17 Feb 2026 13:20:00 GMT"
        )

    monkeypatch.setattr(RssSource, "_request_feed", _request)
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["--no-color", "ingest", "--rss", "https://example.com/feed.xml"],
    )
    assert result.exit_code == 0
    assert "Ingestion completed" in result.output
    assert "succeeded" in result.output
    assert "Run ID" in result.output
    assert "Ingested" in result.output
    assert "Feeds" in result.output
    assert "Cache" in result.output


# ---------------------------------------------------------------------------
# _print_schedule via CLI
# ---------------------------------------------------------------------------


def test_schedule_get_plain_with_feeds(monkeypatch) -> None:
    from news_recap.automation import ScheduleController, ScheduleMeta

    meta = ScheduleMeta(
        time="07:30",
        venv_bin="/my/venv/bin/news-recap",
        agent="claude",
        rss_urls=("https://a.com/rss", "https://b.com/rss"),
    )

    monkeypatch.setattr(ScheduleController, "get_schedule", lambda self: meta)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--no-color", "schedule", "get"])
    assert result.exit_code == 0
    assert "Schedule" in result.output
    assert "07:30" in result.output
    assert "claude" in result.output
    assert "/my/venv/bin/news-recap" in result.output
    assert "Feeds" in result.output
    assert "(2)" in result.output
    assert "https://a.com/rss" in result.output
    assert "https://b.com/rss" in result.output


def test_schedule_get_plain_no_schedule(monkeypatch) -> None:
    from news_recap.automation import ScheduleController

    monkeypatch.setattr(ScheduleController, "get_schedule", lambda self: None)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--no-color", "schedule", "get"])
    assert result.exit_code == 0
    assert "No schedule configured" in result.output


def test_schedule_get_plain_defaults(monkeypatch) -> None:
    from news_recap.automation import ScheduleController, ScheduleMeta

    meta = ScheduleMeta(time="03:00", venv_bin=None, agent=None, rss_urls=())

    monkeypatch.setattr(ScheduleController, "get_schedule", lambda self: meta)
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--no-color", "schedule", "get"])
    assert result.exit_code == 0
    assert "default" in result.output
    assert "no (global news-recap)" in result.output


# ---------------------------------------------------------------------------
# _emit_prompt
# ---------------------------------------------------------------------------


def test_emit_prompt_routes_text_to_plain_echo(capsys) -> None:
    """``"text"`` severity lines are echoed without styling."""
    lines = iter([("info", "Loading..."), ("text", "RAW PROMPT BODY"), ("ok", "Done")])
    _emit_prompt(lines)
    out = capsys.readouterr().out
    assert "RAW PROMPT BODY" in out
    assert "Loading" in out
    assert "Done" in out


# ---------------------------------------------------------------------------
# _emit_run_summary
# ---------------------------------------------------------------------------


def test_emit_run_summary_completed(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "pipeline-2026-03-01-100000"
    _make_digest_on_disk(pipeline_dir, n_articles=5)
    _make_task_dir(pipeline_dir, "classify-1", elapsed=10.5, tokens=500, prompt_text="A" * 1000)

    lines = list(_emit_run_summary(pipeline_dir))
    assert len(lines) >= 2
    ok_line = next(text for sev, text in lines if sev == "ok")
    assert "5 articles" in ok_line
    assert "10s" in ok_line
    log_line = next(text for sev, text in lines if sev == "log")
    assert "Workdir" in log_line
    assert str(pipeline_dir) in log_line


def test_emit_pipeline_prints_stage_table(tmp_path: Path, capsys) -> None:
    """After pipeline lines, _emit_pipeline prints the per-stage table."""
    pipeline_dir = tmp_path / "pipeline-2026-03-01-100000"
    _make_task_dir(pipeline_dir, "classify-1", elapsed=10.5, tokens=500, prompt_text="A" * 1000)
    _make_task_dir(pipeline_dir, "enrich-1", elapsed=5.0, tokens=200, output_text="B" * 300)

    lines: list[tuple[str, str]] = [
        ("ok", "Done: 5 articles, 15s, prompts=1 KB, output=300 B"),
        ("log", f"Workdir: {pipeline_dir}"),
    ]
    _emit_pipeline(iter(lines))
    out = capsys.readouterr().out
    assert "classify-1" in out
    assert "enrich-1" in out


def test_emit_run_summary_no_digest_file(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "empty-dir"
    pipeline_dir.mkdir(parents=True)
    assert list(_emit_run_summary(pipeline_dir)) == []


def test_emit_run_summary_incomplete_digest(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "incomplete"
    _make_digest_on_disk(pipeline_dir, status="in_progress")
    assert list(_emit_run_summary(pipeline_dir)) == []


# ---------------------------------------------------------------------------
# DigestInfoController.digest_detail
# ---------------------------------------------------------------------------


def test_digest_detail_found(tmp_path: Path) -> None:
    from news_recap.recap.pipeline_setup import register_digest

    pdir = tmp_path / "pipeline-2026-03-01-100000"
    arts = [_article()]
    digest = Digest(
        digest_id="d-1",
        run_date="2026-03-01",
        status="completed",
        pipeline_dir=str(pdir),
        articles=arts,
        completed_phases=["classify", "oneshot_digest"],
        coverage_start=arts[0].published_at,
        coverage_end=arts[0].published_at,
    )
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "digest.json").write_bytes(msgspec.json.encode(digest))
    register_digest(tmp_path, pdir, digest)

    settings = MagicMock()
    settings.orchestrator.workdir_root.resolve.return_value = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        result = DigestInfoController().digest_detail(1)
    assert result is not None
    assert result.digest_id == 1
    assert result.article_count == 1


def test_digest_detail_not_found(tmp_path: Path) -> None:
    settings = MagicMock()
    settings.orchestrator.workdir_root.resolve.return_value = tmp_path
    with patch("news_recap.recap.digest_info.Settings.from_env", return_value=settings):
        result = DigestInfoController().digest_detail(99)
    assert result is None


# ---------------------------------------------------------------------------
# --from-digest on prompt command
# ---------------------------------------------------------------------------


def test_prompt_from_digest_loads_articles(tmp_path: Path) -> None:
    """``--from-digest`` loads articles from an existing digest without running the pipeline."""
    from news_recap.recap.export_prompt import PromptCliController, PromptCommand

    digest = Digest(
        digest_id="digest-42",
        run_date="2026-03-10",
        status="completed",
        pipeline_dir=str(tmp_path / "p1"),
        articles=[_article("x1"), _article("x2")],
    )
    pdir = tmp_path / "p1"
    pdir.mkdir(parents=True)
    (pdir / "digest.json").write_bytes(msgspec.json.encode(digest))

    mock_settings = MagicMock()
    mock_settings.orchestrator.workdir_root.resolve.return_value = tmp_path
    mock_settings.dedup.model_name = "test"

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 10, [0.2] * 10]

    digests_index = [
        {
            "digest_id": 1,
            "pipeline_dir_name": "p1",
            "run_date": "2026-03-10",
            "article_count": 2,
        }
    ]
    (tmp_path / "digests.json").write_text(json.dumps(digests_index))

    with (
        patch("news_recap.recap.export_prompt.Settings.from_env", return_value=mock_settings),
        patch("news_recap.recap.export_prompt.recap_flow") as mock_flow,
        patch(
            "news_recap.recap.export_prompt.SentenceTransformerEmbedder",
            return_value=mock_embedder,
        ),
        patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True),
    ):
        controller = PromptCliController()
        output = list(controller.prompt(PromptCommand(from_digest=1, out="clipboard")))

    mock_flow.assert_not_called()
    texts = [text for _, text in output]
    assert any("Loaded 2 articles from digest #1" in t for t in texts)
    assert any("copied" in t.lower() for t in texts)


def test_prompt_from_digest_not_found(tmp_path: Path) -> None:
    """``--from-digest`` with a nonexistent ID raises a ClickException."""
    import click
    import pytest

    from news_recap.recap.export_prompt import PromptCliController, PromptCommand

    mock_settings = MagicMock()
    mock_settings.orchestrator.workdir_root.resolve.return_value = tmp_path

    with (
        patch("news_recap.recap.export_prompt.Settings.from_env", return_value=mock_settings),
        pytest.raises(click.ClickException, match="not found"),
    ):
        controller = PromptCliController()
        list(controller.prompt(PromptCommand(from_digest=999)))
