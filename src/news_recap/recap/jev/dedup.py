"""Duplicate detection on Jev: one "same piece of news?" Noul per candidate pair."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from typesafe_sdk import Noul

from news_recap.recap.dedup.embedder import Vector, cosine_similarity
from news_recap.recap.jev.classify import LEAD_CHARS
from news_recap.recap.jev.client import JevClient
from news_recap.recap.models import DigestArticle

logger = logging.getLogger(__name__)

SAME_EVENT_THRESHOLD = 0.40
# Pairs below the embedding pre-filter are far more often different stories, so the wider net
# asks Jev for more confidence.
WIDE_SIMILARITY = 0.87
WIDE_THRESHOLD = 0.70
# The wider net grows with the square of the night's size; this bounds a catch-up night after
# missed runs (~80 s, ~$0.10) and keeps its most similar pairs.
WIDE_MAX_PAIRS = 5000
PAIR_KEY = "same"
STATE_VARIANTS = ("headline", "lead")
PAIR_STATE = "headline"

# The yes/no criteria carry the editorial rule; without them Jev merges reactions to a story
# and splits one incident reported at different moments.
PAIR_QUESTION = Noul(
    instructions=(
        "Do article_a and article_b report the same piece of news, so that one could replace "
        "the other in a news digest without the reader losing an important fact?"
    ),
    criteria={
        "true": (
            "They report the same event or announcement, including the same incident at "
            "different moments of its development, live coverage and later reports of the "
            "same event, and eyewitness accounts of it."
        ),
        "false": (
            "They report different events, or one of them is a separate piece of news about "
            "the story: a statement, reaction, condemnation, denial, apology or official "
            "assessment by someone, an analysis, explainer or interview, or a roundup that "
            "also covers other stories."
        ),
    },
)


def _article_view(article: DigestArticle, variant: str) -> dict[str, str]:
    view = {"headline": article.enriched_title or article.title}
    if variant == "lead":
        view["source"] = article.source
        view["lead"] = article.clean_text[:LEAD_CHARS]
    return view


def pair_state(
    a: DigestArticle,
    b: DigestArticle,
    variant: str = PAIR_STATE,
) -> dict[str, dict[str, str]]:
    if variant not in STATE_VARIANTS:
        raise ValueError(f"unknown state variant {variant!r}; expected one of {STATE_VARIANTS}")
    return {"article_a": _article_view(a, variant), "article_b": _article_view(b, variant)}


def keeper_order(articles: Sequence[DigestArticle]) -> list[DigestArticle]:
    """Longest text first: the keeper of a merge is the article with the most text."""
    return sorted(articles, key=lambda a: len(a.clean_text), reverse=True)


def star_groups(ids: Sequence[str], same: Callable[[str, str], bool]) -> list[list[str]]:
    """Each id joins the first group whose keeper (first id) it matches, else starts one.

    No chaining: ``b`` matching ``a`` and ``c`` matching ``b`` does not put ``c`` with ``a``.
    Only groups of two or more are returned.

    >>> pairs = {("a", "b"), ("b", "c")}
    >>> star_groups(["a", "b", "c", "d"], lambda x, y: (x, y) in pairs)
    [['a', 'b']]
    >>> star_groups(["a", "b", "c"], lambda x, y: True)
    [['a', 'b', 'c']]
    """
    groups: list[list[str]] = []
    for item in ids:
        for group in groups:
            if same(group[0], item):
                group.append(item)
                break
        else:
            groups.append([item])
    return [g for g in groups if len(g) > 1]


def pair_key(a: DigestArticle, b: DigestArticle) -> tuple[str, str]:
    return (
        (a.article_id, b.article_id)
        if a.article_id < b.article_id
        else (b.article_id, a.article_id)
    )


def candidate_pairs(
    groups: Sequence[Sequence[DigestArticle]],
) -> list[tuple[DigestArticle, DigestArticle]]:
    """Every pair inside each candidate group, each pair once."""
    seen: set[tuple[str, str]] = set()
    pairs = []
    for group in groups:
        for a, b in combinations(group, 2):
            key = pair_key(a, b)
            if key not in seen:
                seen.add(key)
                pairs.append((a, b))
    return pairs


def pair_probabilities(
    client: JevClient,
    pairs: Sequence[tuple[DigestArticle, DigestArticle]],
    variant: str = PAIR_STATE,
) -> dict[tuple[str, str], float]:
    """Return ``pair_key -> probability`` that the two articles are the same piece of news."""
    questions = {PAIR_KEY: PAIR_QUESTION}
    responses = client.decide([(pair_state(a, b, variant), questions) for a, b in pairs])
    return {
        pair_key(a, b): response.nouls[PAIR_KEY].noul
        for (a, b), response in zip(pairs, responses, strict=True)
    }


def merge_groups(
    articles: Sequence[DigestArticle],
    same: Callable[[DigestArticle, DigestArticle], bool],
) -> list[list[DigestArticle]]:
    """Star-group *articles* by *same*; each returned merge group starts with its keeper."""
    ordered = keeper_order(articles)
    by_id = {a.article_id: a for a in ordered}
    ids = star_groups([a.article_id for a in ordered], lambda x, y: same(by_id[x], by_id[y]))
    return [[by_id[i] for i in group] for group in ids]


def wide_pairs(  # noqa: PLR0913
    articles: Sequence[DigestArticle],
    embeddings: Mapping[str, Vector],
    groups: Sequence[Sequence[DigestArticle]],
    high: float,
    low: float = WIDE_SIMILARITY,
    limit: int = WIDE_MAX_PAIRS,
) -> list[tuple[DigestArticle, DigestArticle]]:
    """The *limit* most similar pairs in ``[low, high)`` that no candidate group already holds."""
    group_of = {a.article_id: k for k, group in enumerate(groups) for a in group}
    scored = []
    for a, b in combinations(articles, 2):
        if a.article_id in group_of and group_of.get(b.article_id) == group_of[a.article_id]:
            continue
        similarity = cosine_similarity(embeddings[a.article_id], embeddings[b.article_id])
        if low <= similarity < high:
            scored.append((similarity, a, b))
    if len(scored) > limit:
        logger.warning("dedup: wider net capped at %d of %d pairs", limit, len(scored))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(a, b) for _, a, b in scored[:limit]]


def _components(pairs: set[tuple[str, str]]) -> list[set[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    components: dict[str, set[str]] = {}
    for x in list(parent):
        components.setdefault(find(x), set()).add(x)
    return list(components.values())


@dataclass(frozen=True, slots=True)
class PairAnswer:
    a: DigestArticle
    b: DigestArticle
    probability: float
    wide: bool

    @property
    def same(self) -> bool:
        return self.probability >= (WIDE_THRESHOLD if self.wide else SAME_EVENT_THRESHOLD)


def find_duplicates(
    client: JevClient,
    groups: Sequence[Sequence[DigestArticle]],
    extra_pairs: Sequence[tuple[DigestArticle, DigestArticle]] = (),
) -> tuple[list[list[DigestArticle]], list[PairAnswer]]:
    """Ask Jev about every pair in *groups* plus *extra_pairs* (the wider net).

    Returns the merge groups (keeper first) and every answer.
    """
    group_pairs = candidate_pairs(groups)
    pairs = group_pairs + list(extra_pairs)
    probabilities = pair_probabilities(client, pairs)
    answers = [
        PairAnswer(a, b, probabilities[pair_key(a, b)], wide=i >= len(group_pairs))
        for i, (a, b) in enumerate(pairs)
    ]
    same = {pair_key(x.a, x.b) for x in answers if x.same}
    by_id = {a.article_id: a for x in answers for a in (x.a, x.b)}
    return merges_from(same, by_id), answers


def merges_from(
    same: set[tuple[str, str]],
    by_id: Mapping[str, DigestArticle],
) -> list[list[DigestArticle]]:
    """Star groups inside each connected component of *same* ``pair_key``s, keeper first.

    Components come in a fixed order (by smallest article id).
    """
    return [
        group
        for component in sorted(_components(same), key=min)
        for group in merge_groups(
            [by_id[i] for i in sorted(component)],
            lambda x, y: pair_key(x, y) in same,
        )
    ]
