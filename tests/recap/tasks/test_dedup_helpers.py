from __future__ import annotations

from news_recap.recap.models import DigestArticle
from news_recap.recap.tasks.deduplicate import (
    _MergeAction,
    _apply_merge,
    _find_keeper_id,
    _resolve_merged_articles,
)


def _art(aid: str, clean_text: str = "text") -> DigestArticle:
    return DigestArticle(
        article_id=aid,
        title=f"Title {aid}",
        url=f"https://example.com/{aid}",
        source="test",
        published_at="2026-01-01T00:00:00Z",
        clean_text=clean_text,
    )


def test_resolve_merged_articles_basic() -> None:
    a1, a2, a3 = _art("a"), _art("b"), _art("c")
    group_ids = ["a", "b", "c"]
    id_to_article = {x.article_id: x for x in (a1, a2, a3)}
    merge = _MergeAction(merged_text="m", indices=[1, 3])
    assert _resolve_merged_articles(group_ids, merge, id_to_article) == [a1, a3]


def test_resolve_merged_articles_missing_id() -> None:
    a1, a3 = _art("a"), _art("c")
    group_ids = ["a", "b", "c"]
    id_to_article = {a1.article_id: a1, a3.article_id: a3}
    merge = _MergeAction(merged_text="m", indices=[1, 2, 3])
    assert _resolve_merged_articles(group_ids, merge, id_to_article) == [a1, a3]


def test_apply_merge_keeps_longest() -> None:
    short, mid, long_a = _art("a", "x"), _art("b", "xx"), _art("c", "xxx")
    group_ids = ["a", "b", "c"]
    id_to_article = {short.article_id: short, mid.article_id: mid, long_a.article_id: long_a}
    remove_ids: set[str] = set()
    _apply_merge(
        group_ids, _MergeAction(merged_text="merged", indices=[1, 2, 3]), id_to_article, remove_ids
    )
    assert long_a.article_id not in remove_ids
    assert short.article_id in remove_ids
    assert mid.article_id in remove_ids


def test_apply_merge_sets_enriched_title() -> None:
    a1, a2 = _art("a", "aa"), _art("b", "b")
    group_ids = ["a", "b"]
    id_to_article = {a1.article_id: a1, a2.article_id: a2}
    remove_ids: set[str] = set()
    _apply_merge(
        group_ids, _MergeAction(merged_text="new title", indices=[1, 2]), id_to_article, remove_ids
    )
    keeper = a1 if a1.article_id not in remove_ids else a2
    assert keeper.enriched_title == "new title"


def test_apply_merge_adds_alt_urls() -> None:
    keeper_a = _art("keep", "longer text here")
    other = _art("gone", "x")
    group_ids = ["keep", "gone"]
    id_to_article = {keeper_a.article_id: keeper_a, other.article_id: other}
    remove_ids: set[str] = set()
    _apply_merge(
        group_ids, _MergeAction(merged_text="t", indices=[1, 2]), id_to_article, remove_ids
    )
    assert keeper_a.alt_urls == [{"url": other.url, "source": other.source}]


def test_apply_merge_too_few_articles_noop() -> None:
    a1 = _art("a")
    group_ids = ["a", "b", "c"]
    id_to_article = {a1.article_id: a1}
    remove_ids: set[str] = set()
    _apply_merge(group_ids, _MergeAction(merged_text="m", indices=[1]), id_to_article, remove_ids)
    assert remove_ids == set()
    assert a1.enriched_title is None


def test_find_keeper_id_returns_first_kept() -> None:
    a1, a2, a3 = _art("a"), _art("b"), _art("c")
    group_ids = ["a", "b", "c"]
    id_to_article = {x.article_id: x for x in (a1, a2, a3)}
    merge = _MergeAction(merged_text="m", indices=[1, 2, 3])
    remove_ids = {a2.article_id}
    assert _find_keeper_id(group_ids, merge, id_to_article, remove_ids) == a1.article_id


def test_find_keeper_id_all_removed() -> None:
    a1, a2 = _art("a"), _art("b")
    group_ids = ["a", "b"]
    id_to_article = {a1.article_id: a1, a2.article_id: a2}
    merge = _MergeAction(merged_text="m", indices=[1, 2])
    remove_ids = {a1.article_id, a2.article_id}
    assert _find_keeper_id(group_ids, merge, id_to_article, remove_ids) is None
