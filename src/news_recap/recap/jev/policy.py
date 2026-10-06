"""Parsing of comma-separated free-text topic lists (``exclude``, ``follow``, ``sections``)."""

from __future__ import annotations


def split_policy_topics(text: str) -> list[str]:
    """Split *text* on commas outside parentheses; strip items and drop empty ones.

    >>> split_policy_topics("Croatian domestic news, sports (except Russian sports), horoscopes")
    ['Croatian domestic news', 'sports (except Russian sports)', 'horoscopes']
    >>> split_policy_topics("health advice (diet, sleep, anxiety tips),, ")
    ['health advice (diet, sleep, anxiety tips)']
    >>> split_policy_topics("")
    []
    """
    topics: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            topics.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    topics.append("".join(current).strip())
    return [t for t in topics if t]
