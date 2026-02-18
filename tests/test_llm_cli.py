from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import NormalizedArticle
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.main import news_recap


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
            "--task-manifest {task_manifest}"
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
