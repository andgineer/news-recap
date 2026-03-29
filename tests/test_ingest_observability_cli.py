from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import (
    IngestionRunCounters,
    NormalizedArticle,
    RunStatus,
)
from news_recap.ingestion.repository import IngestionStore
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
