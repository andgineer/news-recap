"""Similarity-based grouping for recap deduplication."""

from __future__ import annotations

from collections import defaultdict, deque

from news_recap.recap.dedup.embedder import Vector, cosine_similarity

_DEFAULT_MAX_GROUP_SIZE = 20
_MIN_GROUP_SIZE = 2


def group_similar(
    ids: list[str],
    embeddings: dict[str, Vector],
    threshold: float,
    max_group_size: int = _DEFAULT_MAX_GROUP_SIZE,
) -> list[list[str]]:
    """Group IDs by pairwise cosine similarity >= *threshold*.

    Returns only groups with 2+ members (singletons are excluded).
    Groups exceeding *max_group_size* are split into sub-groups of
    that size to avoid oversized LLM prompts.

    >>> group_similar([], {}, 0.9)
    []
    """

    if not ids:
        return []

    adjacency = _build_adjacency(ids, embeddings, threshold)
    visited: set[str] = set()
    groups: list[list[str]] = []

    for item_id in ids:
        if item_id in visited:
            continue
        component = _collect_component(item_id, adjacency, visited)
        if len(component) < _MIN_GROUP_SIZE:
            continue
        if len(component) <= max_group_size:
            groups.append(component)
        else:
            for start in range(0, len(component), max_group_size):
                chunk = component[start : start + max_group_size]
                if len(chunk) >= _MIN_GROUP_SIZE:
                    groups.append(chunk)

    return groups


def _build_adjacency(
    ids: list[str],
    embeddings: dict[str, Vector],
    threshold: float,
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for index, left_id in enumerate(ids):
        left_vec = embeddings.get(left_id)
        if left_vec is None:
            continue
        for right_id in ids[index + 1 :]:
            right_vec = embeddings.get(right_id)
            if right_vec is None:
                continue
            if cosine_similarity(left_vec, right_vec) >= threshold:
                adjacency[left_id].add(right_id)
                adjacency[right_id].add(left_id)
    return adjacency


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
