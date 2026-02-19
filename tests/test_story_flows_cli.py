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
from news_recap.orchestrator.contracts import read_manifest
from news_recap.orchestrator.repository import OrchestratorRepository

pytestmark = [
    allure.epic("Product Intelligence"),
    allure.feature("Stories, Monitors, and QA CLI Flows"),
]


def _seed_user_articles(db_path: Path, *, count: int = 3) -> list[str]:
    repo = SQLiteRepository(db_path)
    repo.init_schema()
    run_id = repo.start_run(source="rss")
    source_ids: list[str] = []
    now = datetime.now(tz=UTC)
    for index in range(1, count + 1):
        url = f"https://example.com/news/story-flow-{index}"
        canonical = canonicalize_url(url)
        result = repo.upsert_article(
            article=NormalizedArticle(
                source_name="rss",
                external_id=f"story-flow-{index}",
                url=url,
                url_canonical=canonical,
                url_hash=url_hash(canonical),
                title=f"Story flow headline {index}",
                source_domain=extract_domain(canonical),
                published_at=now,
                language_detected="en",
                content_raw=f"content {index}",
                summary_raw=None,
                is_full_content=True,
                needs_enrichment=False,
                clean_text=f"content {index}",
                clean_text_chars=len(f"content {index}"),
                is_truncated=False,
            ),
            run_id=run_id,
        )
        source_ids.append(f"article:{result.article_id}")
    repo.close()
    return source_ids


def test_highlights_flow_persists_business_output(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "story-highlights.db"
    _seed_user_articles(db_path)
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
    define = runner.invoke(
        news_recap,
        [
            "stories",
            "define",
            "--db-path",
            str(db_path),
            "--name",
            "Serbia updates",
            "--description",
            "serbia updates politics",
            "--target-language",
            "en",
        ],
    )
    assert define.exit_code == 0

    build = runner.invoke(
        news_recap,
        [
            "stories",
            "build",
            "--db-path",
            str(db_path),
        ],
    )
    assert build.exit_code == 0
    assert "Story build completed" in build.output

    enqueue = runner.invoke(
        news_recap,
        [
            "highlights",
            "generate",
            "--db-path",
            str(db_path),
        ],
    )
    assert enqueue.exit_code == 0
    match = re.search(r"task_id=([a-f0-9-]+)", enqueue.output)
    assert match is not None

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

    outputs = runner.invoke(
        news_recap,
        [
            "insights",
            "outputs",
            "--db-path",
            str(db_path),
            "--kind",
            "highlights",
        ],
    )
    assert outputs.exit_code == 0
    assert "kind=highlights" in outputs.output
    assert "blocks=1" in outputs.output


def test_qa_is_append_only_by_request_id(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "story-qa.db"
    _seed_user_articles(db_path)
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
    first = runner.invoke(
        news_recap,
        [
            "qa",
            "ask",
            "--db-path",
            str(db_path),
            "--prompt",
            "What happened today?",
        ],
    )
    second = runner.invoke(
        news_recap,
        [
            "qa",
            "ask",
            "--db-path",
            str(db_path),
            "--prompt",
            "What happened today?",
        ],
    )
    assert first.exit_code == 0
    assert second.exit_code == 0

    worker_once = runner.invoke(
        news_recap,
        [
            "llm",
            "worker",
            "--db-path",
            str(db_path),
            "--once",
        ],
    )
    worker_twice = runner.invoke(
        news_recap,
        [
            "llm",
            "worker",
            "--db-path",
            str(db_path),
            "--once",
        ],
    )
    assert worker_once.exit_code == 0
    assert worker_twice.exit_code == 0

    outputs = runner.invoke(
        news_recap,
        [
            "insights",
            "outputs",
            "--db-path",
            str(db_path),
            "--kind",
            "qa_answer",
        ],
    )
    assert outputs.exit_code == 0
    assert "Outputs: 2" in outputs.output


def test_qa_retrieval_policy_uses_source_id_asc_tiebreak(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "story-qa-retrieval.db"
    _seed_user_articles(db_path)
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
            "qa",
            "ask",
            "--db-path",
            str(db_path),
            "--prompt",
            "What changed?",
        ],
    )
    assert enqueue.exit_code == 0
    match = re.search(r"task_id=([a-f0-9-]+)", enqueue.output)
    assert match is not None
    task_id = match.group(1)

    repository = OrchestratorRepository(db_path)
    repository.init_schema()
    details = repository.get_task_details(task_id=task_id)
    assert details is not None
    manifest = read_manifest(Path(details.task.input_manifest_path))
    assert manifest.retrieval_context_path is not None
    payload = json.loads(Path(manifest.retrieval_context_path).read_text("utf-8"))
    assert payload["ranking_policy"] == "published_at_desc_source_id_asc"

    source_ids = [str(item["source_id"]) for item in payload["items"]]
    assert source_ids == sorted(source_ids)
    repository.close()
