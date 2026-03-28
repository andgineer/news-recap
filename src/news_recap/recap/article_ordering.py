"""Shared helpers for embedding-based article reordering.

Used by both ``export_prompt`` (recap prompt command) and ``tasks/oneshot_digest``
(digest pipeline task).
"""

from __future__ import annotations

from news_recap.recap.dedup.cluster import group_similar
from news_recap.recap.dedup.embedder import Embedder, Vector, cosine_similarity
from news_recap.recap.models import DigestArticle


def _order_cluster(ids: list[str], embeddings: dict[str, Vector]) -> list[str]:
    """Order a cluster using greedy nearest-neighbour from the most central article."""
    remaining = list(ids)
    if len(remaining) == 1:
        return remaining

    start = max(
        remaining,
        key=lambda i: sum(
            cosine_similarity(embeddings[i], embeddings[j]) for j in remaining if j != i
        ),
    )
    ordered = [start]
    remaining.remove(start)
    while remaining:
        last = ordered[-1]
        nxt = max(remaining, key=lambda i: cosine_similarity(embeddings[last], embeddings[i]))
        ordered.append(nxt)
        remaining.remove(nxt)
    return ordered


def reorder_articles(
    articles: list[DigestArticle],
    embedder: Embedder,
    threshold: float,
) -> list[DigestArticle]:
    """Cluster by similarity and apply greedy nearest-neighbour ordering.

    Returns the full article list reordered so similar articles are adjacent.
    """
    if not articles:
        return []

    titles = [a.title for a in articles]
    vectors = embedder.embed(titles)
    ids: list[str] = []
    embeddings: dict[str, Vector] = {}
    articles_by_id: dict[str, DigestArticle] = {}
    for a, v in zip(articles, vectors, strict=True):
        ids.append(a.article_id)
        embeddings[a.article_id] = v
        articles_by_id[a.article_id] = a

    clusters = group_similar(ids, embeddings, threshold, max_group_size=len(articles))

    ordered_clusters = []
    clustered_ids: set[str] = set()
    for cluster in clusters:
        ordered_cluster = _order_cluster(cluster, embeddings)
        ordered_clusters.append(ordered_cluster)
        clustered_ids.update(ordered_cluster)

    singletons = [a for a in articles if a.article_id not in clustered_ids]

    ordered = [articles_by_id[aid] for cluster in ordered_clusters for aid in cluster]
    ordered += singletons
    return ordered


def build_article_lines(ordered: list[DigestArticle], *, include_url: bool = False) -> str:
    """Return numbered article lines for use in an LLM prompt.

    Format per line: "1. Title (source.com)" or "1. Title (source.com) — https://url"
    when *include_url* is True.

    URLs are omitted by default — the pipeline restores them from the article index after parsing.
    No headers, no task section — plain numbered list only.
    """
    if include_url:
        return "\n".join(
            f"{i}. {article.title} ({article.source}) \u2014 {article.url}"
            for i, article in enumerate(ordered, start=1)
        )
    return "\n".join(
        f"{i}. {article.title} ({article.source})" for i, article in enumerate(ordered, start=1)
    )
