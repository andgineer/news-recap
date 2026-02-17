from datetime import UTC, datetime

from news_recap.ingestion.dedup.cluster import cluster_candidates, count_duplicates
from news_recap.ingestion.models import DedupCandidate


def test_cluster_candidates_groups_similar_items() -> None:
    now = datetime.now(tz=UTC)
    candidates = [
        DedupCandidate(
            article_id="a1",
            title="Event one",
            url="https://example.com/a1",
            source_domain="example.com",
            published_at=now,
            clean_text="text",
            clean_text_chars=400,
        ),
        DedupCandidate(
            article_id="a2",
            title="Event one mirror",
            url="https://mirror.example.net/a2",
            source_domain="mirror.example.net",
            published_at=now,
            clean_text="text",
            clean_text_chars=350,
        ),
        DedupCandidate(
            article_id="a3",
            title="Another event",
            url="https://other.org/a3",
            source_domain="other.org",
            published_at=now,
            clean_text="another",
            clean_text_chars=200,
        ),
    ]
    embeddings = {
        "a1": [1.0, 0.0],
        "a2": [0.99, 0.01],
        "a3": [0.0, 1.0],
    }

    clusters = cluster_candidates(candidates=candidates, embeddings=embeddings, threshold=0.95)

    assert len(clusters) == 2
    assert count_duplicates(clusters) == 1
    merged = [cluster for cluster in clusters if len(cluster.members) == 2][0]
    assert merged.representative_article_id == "a1"
    urls = {item["url"] for item in merged.alt_sources}
    assert urls == {"https://example.com/a1", "https://mirror.example.net/a2"}
