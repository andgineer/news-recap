"""Exclude / vague verdicts on Jev: one Noul per exclude-policy topic plus one vague Noul."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from typesafe_sdk import Noul

from news_recap.recap.jev.client import JevClient
from news_recap.recap.jev.policy import split_policy_topics
from news_recap.recap.models import DigestArticle

EXCLUDE_THRESHOLD = 0.75
VAGUE_THRESHOLD = 0.65
LEAD_CHARS = 300
STATE_VARIANTS = ("full", "no_source", "headline_only")
VAGUE_KEY = "vague"

_TOPIC_INSTRUCTIONS = (
    'Is the subject of this news story covered by the excluded topic "{topic}"? Judge by what '
    "the story is about (its events, people, places), not by the country or language of the "
    "outlet that published it. Apply any exception stated in parentheses: a story covered by the "
    "exception is not excluded."
)

VAGUE_QUESTION = Noul(
    instructions=(
        "Does the headline hide the key fact behind a teaser, a rhetorical question or a "
        "deliberate omission (e.g. 'on a popular island…', 'one trend…', 'the secret of…', "
        "'expert revealed…'), so a reader cannot tell what happened without opening the article?"
    ),
)


def topic_question(topic: str) -> Noul:
    return Noul(instructions=_TOPIC_INSTRUCTIONS.format(topic=topic))


def policy_questions(policy: str) -> dict[str, Noul]:
    """Questions keyed ``t0``, ``t1``, … per exclude topic, plus ``vague``.

    >>> sorted(policy_questions("horoscopes, sports (except Russia, Serbia)"))
    ['t0', 't1', 'vague']
    """
    questions = {f"t{i}": topic_question(t) for i, t in enumerate(split_policy_topics(policy))}
    questions[VAGUE_KEY] = VAGUE_QUESTION
    return questions


def article_state(article: DigestArticle, variant: str = "full") -> dict[str, str]:
    if variant not in STATE_VARIANTS:
        raise ValueError(f"unknown state variant {variant!r}; expected one of {STATE_VARIANTS}")
    state = {"headline": article.title}
    if variant == "full":
        state["source"] = article.source
    if variant != "headline_only":
        state["lead"] = article.clean_text[:LEAD_CHARS]
    return state


def verdict(
    probs: Mapping[str, float],
    exclude_threshold: float = EXCLUDE_THRESHOLD,
    vague_threshold: float = VAGUE_THRESHOLD,
) -> str:
    """Any topic at or above *exclude_threshold* excludes; otherwise vague decides.

    >>> verdict({"t0": 0.2, "t1": 0.8, "vague": 0.9}, exclude_threshold=0.75)
    'exclude'
    >>> [verdict({"t0": 0.2, "vague": p}, 0.75, 0.7) for p in (0.7, 0.69)]
    ['vague', 'ok']
    """
    if any(p >= exclude_threshold for key, p in probs.items() if key != VAGUE_KEY):
        return "exclude"
    return "vague" if probs.get(VAGUE_KEY, 0.0) >= vague_threshold else "ok"


def classify_articles(
    client: JevClient,
    articles: Sequence[DigestArticle],
    policy: str,
    variant: str = "full",
) -> dict[str, tuple[str, dict[str, float]]]:
    """Return ``article_id -> (verdict, per-question probabilities)`` for every article."""
    questions = policy_questions(policy)
    responses = client.decide([(article_state(a, variant), questions) for a in articles])
    results: dict[str, tuple[str, dict[str, float]]] = {}
    for article, response in zip(articles, responses, strict=True):
        probs = {key: answer.noul for key, answer in response.nouls.items()}
        results[article.article_id] = (verdict(probs), probs)
    return results
