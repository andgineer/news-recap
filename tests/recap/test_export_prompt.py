"""Tests for export_prompt module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from news_recap.recap.article_ordering import _order_cluster, build_article_lines, reorder_articles
from news_recap.recap.dedup.embedder import HashingEmbedder
from news_recap.recap.export_prompt import (
    PromptCommand,
    PromptCliController,
    _copy_to_clipboard,
    _render_prompt,
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
    assert lines[0] == "1. Title One (example.com)"
    assert lines[1] == "2. Title Two (other.org)"


def test_build_article_lines_with_url() -> None:
    articles = [
        _make_article("a", "Title One", "https://example.com/path", "example.com"),
    ]
    result = build_article_lines(articles, include_url=True)
    assert result == "1. Title One (example.com) \u2014 https://example.com/path"


def test_build_article_lines_empty() -> None:
    assert build_article_lines([]) == ""


# ---------------------------------------------------------------------------
# _render_prompt
# ---------------------------------------------------------------------------


def test_render_prompt_structure() -> None:
    from datetime import date

    articles = [
        _make_article("a", "Some Title", "https://news.com/a", "news.com"),
    ]
    result = _render_prompt(articles, since_date=date(2026, 3, 26), language="en")
    assert "=== 1 ARTICLES (since 2026-03-26) ===" in result
    assert "pre-sorted by topic similarity" in result
    assert "1. Some Title" in result
    assert "=== TASK ===" in result
    assert "digest in English" in result
    assert result.index("=== TASK ===") < result.index("=== 1 ARTICLES")


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


# ---------------------------------------------------------------------------
# PromptCliController --ai path
# ---------------------------------------------------------------------------


def test_prompt_ai_path_runs_pipeline_and_reads_digest(tmp_path: "Path") -> None:  # type: ignore[name-defined]
    """--ai path: recap_flow is called with stop_after=deduplicate and digest.articles used."""
    from datetime import date
    from pathlib import Path

    from news_recap.recap.models import Digest

    article = _make_article("x1", "AI article", "https://ai.com/1", "ai.com")
    digest_obj = Digest(
        digest_id="test-id",
        run_date="2026-03-11",
        status="completed",
        pipeline_dir=str(tmp_path),
        articles=[article],
    )

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path
    mock_settings.ingestion.gc_retention_days = 7
    mock_settings.ingestion.digest_lookback_days = 2
    mock_settings.ingestion.min_resource_chars = 200
    mock_settings.dedup.threshold = 0.90
    mock_settings.dedup.model_name = "intfloat/multilingual-e5-small"
    mock_settings.orchestrator.workdir_root = tmp_path
    mock_settings.orchestrator.default_agent = "claude"
    mock_settings.orchestrator.task_model_map = {}
    mock_settings.orchestrator.claude_command_template = "claude"
    mock_settings.orchestrator.codex_command_template = "codex"
    mock_settings.orchestrator.gemini_command_template = "gemini"
    mock_settings.orchestrator.task_type_timeout_map = {}
    mock_settings.orchestrator.agent_max_parallel = 1
    mock_settings.orchestrator.agent_launch_delay = 0
    mock_settings.orchestrator.execution_backend = "cli"
    mock_settings.orchestrator.api_model_map = {}
    mock_settings.orchestrator.api_max_parallel = 1
    mock_settings.orchestrator.api_concurrency_recovery_successes = 3
    mock_settings.orchestrator.api_downshift_pause_seconds = 1.0
    mock_settings.orchestrator.api_retry_max_backoff_seconds = 60.0
    mock_settings.orchestrator.api_retry_jitter_seconds = 1.0

    mock_store = MagicMock()
    mock_store.list_retrieval_articles.return_value = [article]

    def fake_recap_flow(pipeline_dir: str, run_date: str, stop_after: str | None = None) -> None:
        import msgspec

        pdir = Path(pipeline_dir)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "digest.json").write_bytes(msgspec.json.encode(digest_obj))

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 10]

    since = date(2026, 3, 9)
    with (
        patch("news_recap.recap.export_prompt.Settings.from_env", return_value=mock_settings),
        patch("news_recap.recap.export_prompt.IngestionStore", return_value=mock_store),
        patch(
            "news_recap.recap.export_prompt.recap_flow", side_effect=fake_recap_flow
        ) as mock_flow,
        patch(
            "news_recap.recap.export_prompt.SentenceTransformerEmbedder", return_value=mock_embedder
        ),
        patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True),
        patch(
            "news_recap.recap.export_prompt._compute_article_window",
            return_value=(2, since),
        ),
    ):
        controller = PromptCliController()
        output = list(controller.prompt(PromptCommand(ai=True, out="clipboard")))

    mock_flow.assert_called_once()
    _, kwargs = mock_flow.call_args
    assert kwargs.get("stop_after") == "deduplicate"
    texts = [text for _, text in output]
    assert any("article" in t.lower() or "copied" in t.lower() for t in texts)


def test_prompt_no_ai_path_skips_pipeline(tmp_path: "Path") -> None:  # type: ignore[name-defined]
    """--no-ai path: store is queried directly, recap_flow is never called."""
    from datetime import date
    from pathlib import Path  # noqa: F401

    article = _make_article("y1", "No-AI article", "https://noai.com/1", "noai.com")

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path
    mock_settings.ingestion.gc_retention_days = 7
    mock_settings.ingestion.digest_lookback_days = 2
    mock_settings.dedup.model_name = "intfloat/multilingual-e5-small"

    mock_store = MagicMock()
    mock_store.list_retrieval_articles.return_value = [article]

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 10]

    since = date(2026, 3, 26)
    with (
        patch("news_recap.recap.export_prompt.Settings.from_env", return_value=mock_settings),
        patch("news_recap.recap.export_prompt.IngestionStore", return_value=mock_store),
        patch("news_recap.recap.export_prompt.recap_flow") as mock_flow,
        patch(
            "news_recap.recap.export_prompt.SentenceTransformerEmbedder", return_value=mock_embedder
        ),
        patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True),
        patch(
            "news_recap.recap.export_prompt._compute_article_window",
            return_value=(2, since),
        ),
    ):
        controller = PromptCliController()
        output = list(controller.prompt(PromptCommand(ai=False, out="clipboard")))

    mock_flow.assert_not_called()
    mock_store.list_retrieval_articles.assert_called_once_with(
        lookback_days=2,
        limit=2000,
        since=since,
    )
    texts = [text for _, text in output]
    assert any("copied" in t.lower() for t in texts)


def test_prompt_fresh_flag_bypasses_resume(tmp_path: "Path") -> None:  # type: ignore[name-defined]
    """--fresh: _find_resumable_pipeline is not consulted, new pipeline dir is created."""
    from datetime import date
    from pathlib import Path

    from news_recap.recap.models import Digest

    article = _make_article("z1", "Fresh article", "https://fresh.com/1", "fresh.com")
    digest_obj = Digest(
        digest_id="fresh-id",
        run_date="2026-03-11",
        status="completed",
        pipeline_dir=str(tmp_path),
        articles=[article],
    )

    existing_pdir = tmp_path / "pipeline-2026-03-11-000000"
    existing_pdir.mkdir()
    import msgspec

    (existing_pdir / "digest.json").write_bytes(msgspec.json.encode(digest_obj))

    mock_settings = MagicMock()
    mock_settings.data_dir = tmp_path
    mock_settings.ingestion.gc_retention_days = 7
    mock_settings.ingestion.digest_lookback_days = 2
    mock_settings.ingestion.min_resource_chars = 200
    mock_settings.dedup.threshold = 0.90
    mock_settings.dedup.model_name = "intfloat/multilingual-e5-small"
    mock_settings.orchestrator.workdir_root = tmp_path
    mock_settings.orchestrator.default_agent = "claude"
    mock_settings.orchestrator.task_model_map = {}
    mock_settings.orchestrator.claude_command_template = "claude"
    mock_settings.orchestrator.codex_command_template = "codex"
    mock_settings.orchestrator.gemini_command_template = "gemini"
    mock_settings.orchestrator.task_type_timeout_map = {}
    mock_settings.orchestrator.agent_max_parallel = 1
    mock_settings.orchestrator.agent_launch_delay = 0
    mock_settings.orchestrator.execution_backend = "cli"
    mock_settings.orchestrator.api_model_map = {}
    mock_settings.orchestrator.api_max_parallel = 1
    mock_settings.orchestrator.api_concurrency_recovery_successes = 3
    mock_settings.orchestrator.api_downshift_pause_seconds = 1.0
    mock_settings.orchestrator.api_retry_max_backoff_seconds = 60.0
    mock_settings.orchestrator.api_retry_jitter_seconds = 1.0

    mock_store = MagicMock()
    mock_store.list_retrieval_articles.return_value = [article]

    created_dirs: list[str] = []

    def fake_recap_flow(pipeline_dir: str, run_date: str, stop_after: str | None = None) -> None:
        pdir = Path(pipeline_dir)
        created_dirs.append(pdir.name)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "digest.json").write_bytes(msgspec.json.encode(digest_obj))

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 10]

    since = date(2026, 3, 9)
    with (
        patch("news_recap.recap.export_prompt.Settings.from_env", return_value=mock_settings),
        patch("news_recap.recap.export_prompt.IngestionStore", return_value=mock_store),
        patch("news_recap.recap.export_prompt.recap_flow", side_effect=fake_recap_flow),
        patch(
            "news_recap.recap.export_prompt.SentenceTransformerEmbedder", return_value=mock_embedder
        ),
        patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True),
        patch(
            "news_recap.recap.export_prompt._compute_article_window",
            return_value=(2, since),
        ),
    ):
        controller = PromptCliController()
        list(controller.prompt(PromptCommand(ai=True, fresh=True, out="clipboard")))

    # A new pipeline dir must have been created — not the pre-existing one
    assert created_dirs, "recap_flow was never called"
    assert created_dirs[0] != "pipeline-2026-03-11-000000"
