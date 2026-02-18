from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner

from news_recap.ingestion.cleaning import canonicalize_url, extract_domain, url_hash
from news_recap.ingestion.models import (
    ClusterMember,
    DedupCluster,
    IngestionRunCounters,
    NormalizedArticle,
    RunStatus,
)
from news_recap.ingestion.repository import SQLiteRepository
from news_recap.main import news_recap


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


def _seed_observability_dataset(db_path: Path) -> str:
    repo = SQLiteRepository(db_path)
    repo.init_schema()

    run_id = repo.start_run(source="rss")
    published_at = datetime(2026, 2, 17, 12, 0, tzinfo=UTC)

    first = repo.upsert_article(
        article=_article(
            external_id="stable-1",
            title="France issues red flood alerts",
            url="https://example.com/news/1",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    second = repo.upsert_article(
        article=_article(
            external_id="stable-2",
            title="France flood warnings after heavy rain",
            url="https://example.org/world/2",
            published_at=published_at,
        ),
        run_id=run_id,
    )
    third = repo.upsert_article(
        article=_article(
            external_id="stable-3",
            title="Central bank leaves rates unchanged",
            url="https://example.net/economy/3",
            published_at=published_at,
        ),
        run_id=run_id,
    )

    repo.save_dedup_clusters(
        run_id=run_id,
        model_name="intfloat/multilingual-e5-small",
        threshold=0.95,
        clusters=[
            DedupCluster(
                cluster_id="cluster:1",
                representative_article_id=first.article_id,
                alt_sources=[
                    {"url": "https://example.org/world/2", "source_domain": "example.org"}
                ],
                members=[
                    ClusterMember(
                        article_id=first.article_id,
                        similarity_to_representative=1.0,
                        is_representative=True,
                    ),
                    ClusterMember(
                        article_id=second.article_id,
                        similarity_to_representative=0.97,
                        is_representative=False,
                    ),
                ],
            ),
            DedupCluster(
                cluster_id="cluster:2",
                representative_article_id=third.article_id,
                alt_sources=[],
                members=[
                    ClusterMember(
                        article_id=third.article_id,
                        similarity_to_representative=1.0,
                        is_representative=True,
                    ),
                ],
            ),
        ],
    )

    repo.finish_run(
        run_id=run_id,
        status=RunStatus.SUCCEEDED,
        counters=IngestionRunCounters(
            ingested_count=3,
            updated_count=0,
            skipped_count=0,
            dedup_clusters_count=2,
            dedup_duplicates_count=1,
            gaps_opened_count=0,
        ),
    )
    repo.close()
    return run_id


def test_ingest_stats_command_shows_window_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "observability.db"
    run_id = _seed_observability_dataset(db_path)

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        ["ingest", "stats", "--db-path", str(db_path), "--hours", "24"],
    )

    assert result.exit_code == 0
    assert "Runs: 1" in result.output
    assert "ingested=3" in result.output
    assert "clusters=2" in result.output
    assert "duplicates=1" in result.output
    assert run_id in result.output


def test_ingest_clusters_command_shows_cluster_sizes(tmp_path: Path) -> None:
    db_path = tmp_path / "clusters.db"
    run_id = _seed_observability_dataset(db_path)

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "ingest",
            "clusters",
            "--db-path",
            str(db_path),
            "--run-id",
            run_id,
            "--show-members",
            "--members-per-cluster",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert "Clusters: 2" in result.output
    assert "cluster=cluster:1 size=2" in result.output
    assert "cluster=cluster:2 size=1" in result.output
    assert "REP sim=1.000" in result.output
    assert "DUP sim=0.970" in result.output


def test_ingest_duplicates_command_shows_duplicate_examples(tmp_path: Path) -> None:
    db_path = tmp_path / "duplicates.db"
    run_id = _seed_observability_dataset(db_path)

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "ingest",
            "duplicates",
            "--db-path",
            str(db_path),
            "--run-id",
            run_id,
            "--limit-clusters",
            "5",
            "--members-per-cluster",
            "4",
        ],
    )

    assert result.exit_code == 0
    assert "Duplicate clusters: 1" in result.output
    assert "cluster=cluster:1 size=2" in result.output
    assert "France issues red flood alerts" in result.output
    assert "France flood warnings after heavy rain" in result.output


def test_ingest_prune_command_deletes_articles_older_than_days(tmp_path: Path) -> None:
    db_path = tmp_path / "prune.db"
    repo = SQLiteRepository(db_path)
    repo.init_schema()
    run_id = repo.start_run(source="rss")

    now = datetime.now(tz=UTC)
    old_published_at = now - timedelta(days=40)
    fresh_published_at = now - timedelta(days=3)

    old = repo.upsert_article(
        article=_article(
            external_id="old-ext",
            title="Old article",
            url="https://example.com/news/old",
            published_at=old_published_at,
        ),
        run_id=run_id,
    )
    fresh = repo.upsert_article(
        article=_article(
            external_id="fresh-ext",
            title="Fresh article",
            url="https://example.com/news/fresh",
            published_at=fresh_published_at,
        ),
        run_id=run_id,
    )
    repo._connection.execute(
        "UPDATE user_articles SET discovered_at = ? WHERE user_id = ? AND article_id = ?",
        (old_published_at.isoformat(), repo.user_id, old.article_id),
    )
    repo._connection.execute(
        "UPDATE user_articles SET discovered_at = ? WHERE user_id = ? AND article_id = ?",
        (fresh_published_at.isoformat(), repo.user_id, fresh.article_id),
    )
    repo._connection.commit()
    repo.close()

    runner = CliRunner()
    result = runner.invoke(
        news_recap,
        [
            "ingest",
            "prune",
            "--db-path",
            str(db_path),
            "--days",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert "Retention prune completed: days=30 dry_run=no" in result.output
    assert "Articles deleted: 1" in result.output

    reopened = SQLiteRepository(db_path)
    reopened.init_schema()
    remaining = reopened._connection.execute("SELECT COUNT(*) AS cnt FROM articles").fetchone()
    assert remaining is not None
    assert int(remaining["cnt"]) == 1
    reopened.close()
