from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
from click.testing import CliRunner

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import (
    IngestionRunCounters,
    NormalizedArticle,
    RunStatus,
)
from news_recap.ingestion.repository import IngestionStore
from news_recap.main import news_recap
from news_recap.storage.io import day_key

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Daily Run Observability"),
]


def _article(
    *, external_id: str, title: str, url: str, published_at: datetime
) -> NormalizedArticle:
    canonical = canonicalize_url(url)
    return NormalizedArticle(
        source_name="rss",
        external_id=external_id,
        url=url,
        url_canonical=canonical,
        url_hash=url_hash(canonical),
        title=title,
        source_domain=extract_domain(canonical),
        published_at=published_at,
        language_detected="en",
        content_raw=f"<p>{title}</p>",
        summary_raw=None,
        is_full_content=True,
        needs_enrichment=False,
        clean_text=title,
        clean_text_chars=len(title),
        is_truncated=False,
    )


def _seed_observability_dataset(data_dir: Path) -> str:
    store = IngestionStore(data_dir)

    run_id = store.start_run(source="rss")
    published_at = datetime.now(tz=UTC)

    store.upsert_article(
        article=_article(
            external_id="stable-1",
            title="France issues red flood alerts",
            url="https://example.com/news/1",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    store.upsert_article(
        article=_article(
            external_id="stable-2",
            title="France flood warnings after heavy rain",
            url="https://example.org/world/2",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    store.upsert_article(
        article=_article(
            external_id="stable-3",
            title="Central bank leaves rates unchanged",
            url="https://example.net/economy/3",
            published_at=published_at,
        ),
        run_id=run_id,
    )

    store.finish_run(
        run_id=run_id,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(
            ingested_count=3,
            updated_count=0,
            skipped_count=0,
            gaps_opened_count=0,
        ),
    )
    store.close()
    return run_id


def test_ingest_stats_command_shows_window_metrics(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "observability-data"
    run_id = _seed_observability_dataset(data_dir)
    monkeypatch.setenv("NEWS_RECAP_DATA_DIR", str(data_dir))

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["ingest", "stats", "--hours", "24"],
    )

    assert result.exit_code == 0
    assert "Runs: 1" in result.output
    assert "ingested=3" in result.output
    assert run_id in result.output


def test_auto_gc_deletes_old_daily_partitions_on_init(tmp_path: Path) -> None:
    data_dir = tmp_path / "auto-gc-data"
    store = IngestionStore(data_dir, gc_retention_days=7)
    run_id = store.start_run(source="rss")

    now = datetime.now(tz=UTC)
    old_published_at = now - timedelta(days=10)

    store.upsert_article(
        article=_article(
            external_id="orphan-ext",
            title="Orphan article",
            url="https://example.com/news/orphan",
            published_at=old_published_at,
        ),
        run_id=run_id,
    )
    store.finish_run(
        run_id=run_id,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(ingested_count=1),
    )
    store.close()

    old_dk = day_key(old_published_at)
    assert (data_dir / "ingestion" / f"articles-{old_dk}.json").exists()

    reopened = IngestionStore(data_dir, gc_retention_days=7)
    reopened.init_schema()
    assert not (data_dir / "ingestion" / f"articles-{old_dk}.json").exists()
