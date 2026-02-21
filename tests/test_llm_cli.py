from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import allure
from click.testing import CliRunner

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import NormalizedArticle
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.main import news_recap

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Routing, Failures, CLI Ops"),
]


def _seed_user_article(db_path: Path) -> str:
    repo = SQLiteRepository(db_path)
    repo.init_schema()
    run_id = repo.start_run(source="rss")
    url = "https://example.com/news/cli-seed"
    canonical = canonicalize_url(url)
    result = repo.upsert_article(
        article=NormalizedArticle(
            source_name="rss",
            external_id="cli-seed",
            url=url,
            url_canonical=canonical,
            url_hash=url_hash(canonical),
            title="CLI Seed Article",
            source_domain=extract_domain(canonical),
            published_at=datetime(2026, 2, 18, 12, 0, tzinfo=UTC),
            language_detected="en",
            content_raw="seed",
            summary_raw=None,
            is_full_content=True,
            needs_enrichment=False,
            clean_text="seed",
            clean_text_chars=4,
            is_truncated=False,
        ),
        run_id=run_id,
    )
    repo.close()
    return f"article:{result.article_id}"


def test_llm_cli_enqueue_worker_and_inspect(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "llm-cli.db"
    source_id = _seed_user_article(db_path)
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex")
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE",
        (
            f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
            "--prompt-file {prompt_file}"
        ),
    )
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKDIR_ROOT", str(tmp_path / "workdir"))

    runner = CliRunner()
    enqueue = runner.invoke(
        news_recap,
        [
            "llm",
            "enqueue-test",
            "--db-path",
            str(db_path),
            "--task-type",
            "highlights",
            "--prompt",
            "Generate highlights.",
            "--source-id",
            source_id,
        ],
    )
    assert enqueue.exit_code == 0
    match = re.search(r"task_id=([a-f0-9-]+)", enqueue.output)
    assert match is not None
    task_id = match.group(1)

    worker = runner.invoke(
        news_recap,
        [
            "llm",
            "worker",
            "--db-path",
            str(db_path),
            "--once",
        ],
    )
    assert worker.exit_code == 0
    assert "processed=1" in worker.output
    assert "succeeded=1" in worker.output

    tasks = runner.invoke(
        news_recap,
        [
            "llm",
            "tasks",
            "--db-path",
            str(db_path),
            "--status",
            "succeeded",
        ],
    )
    assert tasks.exit_code == 0
    assert task_id in tasks.output

    inspect = runner.invoke(
        news_recap,
        [
            "llm",
            "inspect",
            "--db-path",
            str(db_path),
            "--task-id",
            task_id,
        ],
    )
    assert inspect.exit_code == 0
    assert "Status: succeeded" in inspect.output

    usage = runner.invoke(
        news_recap,
        [
            "llm",
            "usage",
            "--db-path",
            str(db_path),
            "--task-id",
            task_id,
        ],
    )
    assert usage.exit_code == 0
    assert "Attempts telemetry: 1" in usage.output

    failures = runner.invoke(
        news_recap,
        [
            "llm",
            "failures",
            "--db-path",
            str(db_path),
            "--hours",
            "24",
        ],
    )
    assert failures.exit_code == 0
    assert "Failed attempts:" in failures.output

    cost = runner.invoke(
        news_recap,
        [
            "llm",
            "cost",
            "--db-path",
            str(db_path),
            "--hours",
            "24",
            "--group-by",
            "model",
        ],
    )
    assert cost.exit_code == 0
    assert "Cost summary:" in cost.output


def test_llm_cli_stats_reports_queue_and_validation_metrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "llm-cli-stats.db"
    source_id = _seed_user_article(db_path)
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex")
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE",
        (
            f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
            "--prompt-file {prompt_file}"
        ),
    )
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKDIR_ROOT", str(tmp_path / "workdir"))

    runner = CliRunner()
    enqueue = runner.invoke(
        news_recap,
        [
            "llm",
            "enqueue-test",
            "--db-path",
            str(db_path),
            "--task-type",
            "highlights",
            "--prompt",
            "Generate highlights.",
            "--source-id",
            source_id,
        ],
    )
    assert enqueue.exit_code == 0

    worker = runner.invoke(
        news_recap,
        [
            "llm",
            "worker",
            "--db-path",
            str(db_path),
            "--once",
        ],
    )
    assert worker.exit_code == 0
    assert "succeeded=1" in worker.output

    stats = runner.invoke(
        news_recap,
        [
            "llm",
            "stats",
            "--db-path",
            str(db_path),
            "--hours",
            "24",
        ],
    )
    assert stats.exit_code == 0
    assert "LLM queue health (window=24h)" in stats.output
    assert "Validation failures: output_invalid_json=0 source_mapping_failed=0" in stats.output
    assert "Latency percentiles" in stats.output
    assert "Attempt-level metrics: total=1" in stats.output
    assert "missing_output_rate=0.00%" in stats.output


def test_llm_cli_benchmark_writes_report(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "llm-cli-benchmark.db"
    _seed_user_article(db_path)
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKDIR_ROOT", str(tmp_path / "workdir"))

    report_path = tmp_path / "benchmark_report.md"
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "llm",
            "benchmark",
            "--db-path",
            str(db_path),
            "--tasks-per-type",
            "2",
            "--output",
            str(report_path),
        ],
    )
    assert result.exit_code == 0
    assert "Benchmark matrix completed:" in result.output
    assert f"Benchmark report written: {report_path}" in result.output

    report_text = report_path.read_text("utf-8")
    assert "# Epic 2 Benchmark Report" in report_text
    assert "Go/No-Go recommendation:" in report_text
    assert "--use-benchmark-agent" in report_text


def test_llm_cli_benchmark_report_reflects_configured_agent_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "llm-cli-benchmark-configured.db"
    _seed_user_article(db_path)
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex")
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE",
        (
            f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
            "--prompt-file {prompt_file}"
        ),
    )
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKDIR_ROOT", str(tmp_path / "workdir"))

    report_path = tmp_path / "benchmark_report_configured.md"
    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "llm",
            "benchmark",
            "--db-path",
            str(db_path),
            "--task-type",
            "highlights",
            "--tasks-per-type",
            "1",
            "--use-configured-agent",
            "--output",
            str(report_path),
        ],
    )
    assert result.exit_code == 0

    report_text = report_path.read_text("utf-8")
    assert "--use-configured-agent" in report_text


def _extract_json(output: str) -> dict:
    """Extract JSON object from CLI output that may include log lines."""
    start = output.index("{")
    return json.loads(output[start:])


def test_llm_failures_json_format(tmp_path: Path, monkeypatch) -> None:
    """llm failures --format json outputs valid JSON."""
    db_path = tmp_path / "failures-json.db"
    monkeypatch.setenv("NEWS_RECAP_DB_PATH", str(db_path))
    runner = CliRunner()
    result = runner.invoke(
        news_recap, ["llm", "failures", "--format", "json", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0
    parsed = _extract_json(result.output)
    assert "failures" in parsed
    assert "window_hours" in parsed
    assert "count" in parsed


def test_llm_usage_json_format(tmp_path: Path, monkeypatch) -> None:
    """llm usage --format json outputs valid JSON with attempt entries."""
    db_path = tmp_path / "usage-json.db"
    source_id = _seed_user_article(db_path)
    monkeypatch.setenv("NEWS_RECAP_LLM_DEFAULT_AGENT", "codex")
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE",
        (
            f"{sys.executable} -m news_recap.orchestrator.backend.echo_agent "
            "--prompt-file {prompt_file}"
        ),
    )
    monkeypatch.setenv("NEWS_RECAP_LLM_WORKDIR_ROOT", str(tmp_path / "workdir"))

    runner = CliRunner()
    enqueue = runner.invoke(
        news_recap,
        [
            "llm",
            "enqueue-test",
            "--db-path",
            str(db_path),
            "--task-type",
            "highlights",
            "--prompt",
            "JSON usage test.",
            "--source-id",
            source_id,
        ],
    )
    assert enqueue.exit_code == 0
    match = re.search(r"task_id=([a-f0-9-]+)", enqueue.output)
    assert match is not None
    task_id = match.group(1)

    worker = runner.invoke(news_recap, ["llm", "worker", "--db-path", str(db_path), "--once"])
    assert worker.exit_code == 0

    result = runner.invoke(
        news_recap,
        ["llm", "usage", "--format", "json", "--db-path", str(db_path), "--task-id", task_id],
    )
    assert result.exit_code == 0
    parsed = _extract_json(result.output)
    assert parsed["task_id"] == task_id
    assert "attempts" in parsed
    assert len(parsed["attempts"]) == 1
    assert "status" in parsed
    assert "task_type" in parsed


def test_llm_cost_json_format(tmp_path: Path, monkeypatch) -> None:
    """llm cost --format json outputs valid JSON."""
    db_path = tmp_path / "cost-json.db"
    monkeypatch.setenv("NEWS_RECAP_DB_PATH", str(db_path))
    runner = CliRunner()
    result = runner.invoke(
        news_recap, ["llm", "cost", "--format", "json", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0
    parsed = _extract_json(result.output)
    assert "groups" in parsed
    assert "group_by" in parsed
    assert "window_hours" in parsed
