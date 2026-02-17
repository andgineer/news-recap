"""Clustering logic for semantic deduplication."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque

from news_recap.ingestion.dedup.embedder import Vector, cosine_similarity
from news_recap.ingestion.models import ClusterMember, DedupCandidate, DedupCluster


def cluster_candidates(
    candidates: list[DedupCandidate],
    embeddings: dict[str, Vector],
    threshold: float,
) -> list[DedupCluster]:
    """Cluster candidates by pairwise similarity threshold."""

    if not candidates:
        return []

    id_to_candidate = {candidate.article_id: candidate for candidate in candidates}
    adjacency = _build_adjacency(candidates, embeddings, threshold)

    visited: set[str] = set()
    clusters: list[DedupCluster] = [
        _build_cluster(component_candidates, embeddings)
        for component_candidates in _iter_component_candidates(
            candidates=candidates,
            id_to_candidate=id_to_candidate,
            adjacency=adjacency,
            visited=visited,
        )
    ]
    return clusters


def count_duplicates(clusters: list[DedupCluster]) -> int:
    """Count duplicate (non-representative) items across all clusters."""

    duplicates = 0
    for cluster in clusters:
        for member in cluster.members:
            if not member.is_representative:
                duplicates += 1
    return duplicates


def _build_adjacency(
    candidates: list[DedupCandidate],
    embeddings: dict[str, Vector],
    threshold: float,
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for index, left in enumerate(candidates):
        left_vec = embeddings.get(left.article_id)
        if left_vec is None:
            continue
        for right in candidates[index + 1 :]:
            right_vec = embeddings.get(right.article_id)
            if right_vec is None:
                continue
            if cosine_similarity(left_vec, right_vec) >= threshold:
                adjacency[left.article_id].add(right.article_id)
                adjacency[right.article_id].add(left.article_id)
    return adjacency


def _iter_component_candidates(
    *,
    candidates: list[DedupCandidate],
    id_to_candidate: dict[str, DedupCandidate],
    adjacency: dict[str, set[str]],
    visited: set[str],
) -> list[list[DedupCandidate]]:
    components: list[list[DedupCandidate]] = []
    for candidate in candidates:
        article_id = candidate.article_id
        if article_id in visited:
            continue
        component_ids = _collect_component(article_id, adjacency, visited)
        components.append([id_to_candidate[item_id] for item_id in component_ids])
    return components


def _build_cluster(
    candidates: list[DedupCandidate],
    embeddings: dict[str, Vector],
) -> DedupCluster:
    representative = _choose_representative(candidates)
    representative_vec = embeddings.get(representative.article_id)

    members: list[ClusterMember] = []
    for candidate in sorted(candidates, key=lambda item: item.article_id):
        member_vec = embeddings.get(candidate.article_id)
        similarity = (
            cosine_similarity(representative_vec, member_vec)
            if representative_vec is not None and member_vec is not None
            else 1.0
        )
        members.append(
            ClusterMember(
                article_id=candidate.article_id,
                similarity_to_representative=similarity,
                is_representative=candidate.article_id == representative.article_id,
            ),
        )

    return DedupCluster(
        cluster_id=_build_cluster_id([member.article_id for member in members]),
        representative_article_id=representative.article_id,
        alt_sources=_build_alt_sources(candidates),
        members=members,
    )


def _collect_component(
    start_id: str,
    adjacency: dict[str, set[str]],
    visited: set[str],
) -> list[str]:
    queue: deque[str] = deque([start_id])
    component: list[str] = []

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        component.append(current)
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    return component


def _choose_representative(candidates: list[DedupCandidate]) -> DedupCandidate:
    return sorted(
        candidates,
        key=lambda item: (-item.clean_text_chars, item.published_at, item.article_id),
    )[0]


def _build_alt_sources(candidates: list[DedupCandidate]) -> list[dict[str, str]]:
    alt_sources = {
        (candidate.url, candidate.source_domain): {
            "url": candidate.url,
            "domain": candidate.source_domain,
        }
        for candidate in candidates
    }
    return [
        alt_sources[key] for key in sorted(alt_sources.keys(), key=lambda pair: (pair[1], pair[0]))
    ]


def _build_cluster_id(article_ids: list[str]) -> str:
    joined = "|".join(sorted(article_ids))
    digest = hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324
    return f"cluster:{digest}"
