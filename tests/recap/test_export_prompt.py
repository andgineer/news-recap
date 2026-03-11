"""Tests for export_prompt module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from news_recap.recap.dedup.embedder import HashingEmbedder
from news_recap.recap.export_prompt import (
    _copy_to_clipboard,
    _order_cluster,
    _render_prompt,
    build_article_lines,
    reorder_articles,
)
from news_recap.recap.models import DigestArticle


def _make_article(
    article_id: str, title: str, url: str = "", source: str = "test.com"
) -> DigestArticle:
    return DigestArticle(
        article_id=article_id,
        title=title,
        url=url or f"https://{source}/{article_id}",
        source=source,
        published_at="2026-03-10T00:00:00Z",
        clean_text="",
    )


# ---------------------------------------------------------------------------
# _order_cluster
# ---------------------------------------------------------------------------


def test_order_cluster_single() -> None:
    embedder = HashingEmbedder(model_name="test")
    texts = ["only article"]
    vectors = embedder.embed(texts)
    embeddings = {"a1": vectors[0]}
    result = _order_cluster(["a1"], embeddings)
    assert result == ["a1"]


def test_order_cluster_adjacent_similarity() -> None:
    """Articles with similar titles should end up adjacent."""
    embedder = HashingEmbedder(model_name="test")
    articles = [
        _make_article("a", "Ukraine war ceasefire talks in Berlin"),
        _make_article("b", "Ukraine war ceasefire talks in Paris"),
        _make_article("c", "Stock market rally on Wall Street"),
    ]
    titles = [a.title for a in articles]
    vectors = embedder.embed(titles)
    embeddings = {a.article_id: v for a, v in zip(articles, vectors, strict=True)}

    ordered = _order_cluster(["a", "b", "c"], embeddings)
    # "a" and "b" are about the same topic; "c" is unrelated.
    # Expect "a" and "b" to be adjacent (positions 0&1 or 1&2).
    assert set(ordered[:2]) == {"a", "b"} or set(ordered[1:]) == {"a", "b"}


# ---------------------------------------------------------------------------
# reorder_articles
# ---------------------------------------------------------------------------


def test_reorder_articles_empty() -> None:
    embedder = HashingEmbedder(model_name="test")
    assert reorder_articles([], embedder, 0.65) == []


def test_reorder_articles_singleton_recovery() -> None:
    """An article that forms no cluster (singleton) must still appear in output."""
    embedder = HashingEmbedder(model_name="test")
    articles = [
        _make_article("a", "Ukraine war ceasefire talks in Berlin"),
        _make_article("b", "Ukraine war ceasefire talks in Paris"),
        _make_article("c", "Stock market rally Wall Street"),  # unrelated singleton
    ]
    ordered = reorder_articles(articles, embedder, threshold=0.65)
    assert len(ordered) == 3
    assert {a.article_id for a in ordered} == {"a", "b", "c"}
    # singleton "c" should be at the end
    assert ordered[-1].article_id == "c"


def test_reorder_articles_all_singletons() -> None:
    """When no clusters form, all articles are returned as singletons in original order."""
    embedder = HashingEmbedder(model_name="test")
    articles = [
        _make_article("a", "Ukraine war ceasefire"),
        _make_article("b", "Stock market rally"),
        _make_article("c", "Football World Cup"),
    ]
    ordered = reorder_articles(articles, embedder, threshold=0.99)
    assert len(ordered) == 3
    assert [a.article_id for a in ordered] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# build_article_lines
# ---------------------------------------------------------------------------


def test_build_article_lines_format() -> None:
    articles = [
        _make_article("a", "Title One", "https://example.com/path", "example.com"),
        _make_article("b", "Title Two", "https://other.org/news", "other.org"),
    ]
    result = build_article_lines(articles)
    lines = result.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("1. Title One (example.com) \u2014 https://example.com/path")
    assert lines[1].startswith("2. Title Two (other.org) \u2014 https://other.org/news")


def test_build_article_lines_empty() -> None:
    assert build_article_lines([]) == ""


# ---------------------------------------------------------------------------
# _render_prompt
# ---------------------------------------------------------------------------


def test_render_prompt_structure() -> None:
    articles = [
        _make_article("a", "Some Title", "https://news.com/a", "news.com"),
    ]
    result = _render_prompt(articles, lookback_days=2, language="en")
    assert "=== 1 ARTICLES (last 2 day(s)) ===" in result
    assert "pre-sorted by topic similarity" in result
    assert "1. Some Title" in result
    assert "=== TASK ===" in result
    assert "digest in en" in result


# ---------------------------------------------------------------------------
# _copy_to_clipboard fallback
# ---------------------------------------------------------------------------


def test_copy_to_clipboard_falls_back_when_no_command() -> None:
    """When all clipboard commands fail, _copy_to_clipboard returns False."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = _copy_to_clipboard("test text")
    assert result is False


def test_copy_to_clipboard_succeeds_on_first_working_command() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = _copy_to_clipboard("test text")
    assert result is True
    assert mock_run.call_count == 1
