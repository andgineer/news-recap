"""Tests for intelligence-domain methods on SQLiteRepository.

Covers: source-id validation, outputs, read-state, feedback, and
block-scope enforcement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import allure
import pytest

from news_recap.brain.models import (
    OutputFeedbackWrite,
    ReadStateEventWrite,
    UserOutputBlockWrite,
    UserOutputUpsert,
)
from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import NormalizedArticle
from news_recap.ingestion.repository import SQLiteRepository

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Intelligence Repository"),
]


def _seed_article(repo: SQLiteRepository, *, external_id: str = "seed-1") -> str:
    """Ingest one article and return its article_id."""
    run_id = repo.start_run(source="rss")
    url = f"https://example.com/news/{external_id}"
    canonical = canonicalize_url(url)
    result = repo.upsert_article(
        article=NormalizedArticle(
            source_name="rss",
            external_id=external_id,
            url=url,
            url_canonical=canonical,
            url_hash=url_hash(canonical),
            title=f"Headline {external_id}",
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
    return result.article_id


def test_validate_user_source_ids_is_user_scoped(tmp_path: Path) -> None:
    db_path = tmp_path / "source-scope.db"

    repo_a = SQLiteRepository(db_path, user_id="user_a", user_name="User A")
    repo_a.init_schema()
    article_id = _seed_article(repo_a, external_id="shared-1")
    source_id = f"article:{article_id}"

    resolved_a, missing_a = repo_a.validate_user_source_ids(source_ids=(source_id,))
    assert missing_a == []
    assert len(resolved_a) == 1
    assert resolved_a[0].source_id == source_id
    repo_a.close()

    repo_b = SQLiteRepository(db_path, user_id="user_b", user_name="User B")
    repo_b.init_schema()
    resolved_b, missing_b = repo_b.validate_user_source_ids(source_ids=(source_id,))
    assert resolved_b == []
    assert missing_b == [source_id]
    repo_b.close()


def test_read_state_and_feedback_reject_mismatched_output_block_scope(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "output-scope.db")
    repository.init_schema()

    output_a = repository.upsert_user_output(
        UserOutputUpsert(
            kind="highlights",
            business_date=date(2026, 2, 18),
            status="ready",
            payload={"kind": "a"},
            blocks=[
                UserOutputBlockWrite(
                    block_order=0,
                    text="A",
                    source_ids=("article:a",),
                ),
            ],
        ),
    )
    output_b = repository.upsert_user_output(
        UserOutputUpsert(
            kind="qa_answer",
            business_date=date(2026, 2, 18),
            status="ready",
            request_id="request-b",
            payload={"kind": "b"},
            blocks=[
                UserOutputBlockWrite(
                    block_order=0,
                    text="B",
                    source_ids=("article:b",),
                ),
            ],
        ),
    )

    row_b = repository._connection.execute(
        "SELECT block_id FROM user_output_blocks WHERE user_id = ? AND output_id = ? LIMIT 1",
        (repository.user_id, output_b.output_id),
    ).fetchone()
    assert row_b is not None
    block_b_id = int(row_b["block_id"])

    with pytest.raises(ValueError, match="does not belong to output"):
        repository.add_read_state_event(
            ReadStateEventWrite(
                output_id=output_a.output_id,
                output_block_id=block_b_id,
                event_type="open",
            ),
        )

    with pytest.raises(ValueError, match="does not belong to output"):
        repository.add_output_feedback(
            OutputFeedbackWrite(
                output_id=output_a.output_id,
                output_block_id=block_b_id,
                feedback_type="hide",
            ),
        )
    repository.close()


def test_list_recent_read_source_ids_respects_block_scope(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "read-state-scope.db")
    repository.init_schema()

    output = repository.upsert_user_output(
        UserOutputUpsert(
            kind="highlights",
            business_date=date(2026, 2, 18),
            status="ready",
            payload={"summary": "test"},
            blocks=[
                UserOutputBlockWrite(
                    block_order=0,
                    text="Block 1",
                    source_ids=("article:1",),
                ),
                UserOutputBlockWrite(
                    block_order=1,
                    text="Block 2",
                    source_ids=("article:2",),
                ),
            ],
        ),
    )

    rows = repository._connection.execute(
        "SELECT block_id, block_order FROM user_output_blocks "
        "WHERE user_id = ? AND output_id = ? ORDER BY block_order",
        (repository.user_id, output.output_id),
    ).fetchall()
    assert len(rows) == 2
    first_block_id = int(rows[0]["block_id"])

    repository.add_read_state_event(
        ReadStateEventWrite(
            output_id=output.output_id,
            output_block_id=first_block_id,
            event_type="open",
        ),
    )
    repository.add_read_state_event(
        ReadStateEventWrite(
            output_id=output.output_id,
            output_block_id=None,
            event_type="open",
        ),
    )

    seen = repository.list_recent_read_source_ids(days=3)
    assert seen == {"article:1"}
    repository.close()


def test_build_retrieval_context_ranking_and_truncation(tmp_path: Path) -> None:
    """_build_retrieval_context ranks published_at DESC / source_id ASC and truncates."""
    from news_recap.brain.flows import _build_retrieval_context
    from news_recap.config import Settings

    db_path = tmp_path / "retrieval-ranking.db"
    repo = SQLiteRepository(db_path)
    repo.init_schema()

    today = date.today()
    ts_old = datetime(today.year, today.month, today.day, 6, 0, tzinfo=UTC)
    ts_new = datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC)

    run_id = repo.start_run(source="rss")
    ids = []
    for ext_id, ts in [("old-b", ts_old), ("old-a", ts_old), ("new-z", ts_new)]:
        url = f"https://example.com/{ext_id}"
        canonical = canonicalize_url(url)
        result = repo.upsert_article(
            article=NormalizedArticle(
                source_name="rss",
                external_id=ext_id,
                url=url,
                url_canonical=canonical,
                url_hash=url_hash(canonical),
                title=f"Title {ext_id}",
                source_domain=extract_domain(canonical),
                published_at=ts,
                language_detected="en",
                content_raw="text",
                summary_raw=None,
                is_full_content=True,
                needs_enrichment=False,
                clean_text="text",
                clean_text_chars=4,
                is_truncated=False,
            ),
            run_id=run_id,
        )
        ids.append(f"article:{result.article_id}")

    settings = Settings.from_env()
    entries, ctx = _build_retrieval_context(
        repository=repo,
        settings=settings,
        business_date=today,
        lookback_days=7,
    )
    result_ids = [e.source_id for e in entries]

    assert result_ids[0] == ids[2], "newest article must be first"
    old_ids = result_ids[1:]
    assert old_ids == sorted(old_ids), "same-timestamp articles sorted by source_id ASC"

    assert ctx["ranking_policy"] == "published_at_desc_source_id_asc"
    items = ctx["items"]
    assert isinstance(items, list)
    assert len(items) == len(entries)
    assert all(items[i]["rank"] == i + 1 for i in range(len(items)))

    settings.orchestrator.retrieval_top_k = 2
    settings.orchestrator.retrieval_max_articles = 2
    truncated, trunc_ctx = _build_retrieval_context(
        repository=repo,
        settings=settings,
        business_date=today,
        lookback_days=7,
    )
    assert len(truncated) == 2, "must truncate to min(top_k, max_articles)"
    assert truncated[0].source_id == ids[2], "newest article still first after truncation"

    repo.close()
