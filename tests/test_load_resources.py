"""Tests for LoadResources task launcher."""

from __future__ import annotations

import pytest

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.models import DigestArticle


class TestLoadResources:
    """Tests for ``LoadResources`` task launcher."""

    def _make_digest_article(self, aid, verdict="vague", resource_loaded=False):
        return DigestArticle(
            article_id=aid,
            title=f"Title {aid}",
            url=f"https://example.com/{aid}",
            source="test",
            published_at="2026-02-17T00:00:00+00:00",
            clean_text="body",
            verdict=verdict,
            resource_loaded=resource_loaded,
        )

    def _make_ctx(self, tmp_path, articles, enrich_ids):
        from datetime import date
        from unittest.mock import MagicMock

        from news_recap.recap.models import Digest
        from news_recap.recap.storage.pipeline_io import PipelineInput
        from news_recap.recap.tasks.base import FlowContext, PipelineRunResult

        pdir = tmp_path / "pipeline"
        pdir.mkdir()

        inp = MagicMock(spec=PipelineInput)
        inp.min_resource_chars = 50
        inp.articles = articles

        digest = Digest(
            digest_id="test-digest",
            business_date="2026-01-01",
            status="running",
            pipeline_dir=str(pdir),
            articles=list(articles),
        )

        article_entries = [
            ArticleIndexEntry(
                source_id=a.article_id,
                title=a.title,
                url=a.url,
                source=a.source,
            )
            for a in articles
        ]

        result = PipelineRunResult(pipeline_id="test", business_date=date(2026, 1, 1))
        workdir_mgr = MagicMock()

        ctx = FlowContext(
            pdir=pdir,
            workdir_mgr=workdir_mgr,
            inp=inp,
            article_map={e.source_id: e for e in article_entries},
            result=result,
            digest=digest,
        )
        ctx.state["enrich_ids"] = enrich_ids
        return ctx

    def test_no_enrich_ids_skips(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [self._make_digest_article("a1", verdict="ok")]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[])

        with patch.object(lr_mod, "get_run_logger"):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.state["enrich_ids"] == []

    def test_loads_and_marks(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="follow"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2"])

        loaded = {"a1": ("Title a1", "text " * 50), "a2": ("Title a2", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[0].resource_loaded is True
        assert ctx.digest.articles[1].resource_loaded is True
        assert set(ctx.state["enrich_ids"]) == {"a1", "a2"}
        assert lr.fully_completed is True

    def test_failed_resources_reset_verdict(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="follow"),
            self._make_digest_article("a3", verdict="vague"),
            self._make_digest_article("a4", verdict="vague"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2", "a3", "a4"])

        loaded = {
            "a1": ("Title a1", "text " * 50),
            "a3": ("Title a3", "text " * 50),
            "a4": ("Title a4", "text " * 50),
        }

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[0].resource_loaded is True
        assert ctx.digest.articles[0].verdict == "vague"
        assert ctx.digest.articles[1].resource_loaded is False
        assert ctx.digest.articles[1].verdict == "ok"
        assert ctx.digest.articles[2].resource_loaded is True
        assert "a2" not in ctx.state["enrich_ids"]
        assert "a1" in ctx.state["enrich_ids"]

    def test_high_failure_rate_raises(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod
        from news_recap.recap.tasks.base import RecapPipelineError

        articles = [self._make_digest_article(f"a{i}", verdict="vague") for i in range(10)]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[f"a{i}" for i in range(10)])

        loaded = {f"a{i}": (f"Title a{i}", "text " * 50) for i in range(5)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            with pytest.raises(RecapPipelineError):
                lr.execute()

    def test_already_loaded_skipped(self, tmp_path):
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague", resource_loaded=True),
            self._make_digest_article("a2", verdict="vague"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2"])

        loaded = {"a2": ("Title a2", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[1].resource_loaded is True
        assert set(ctx.state["enrich_ids"]) == {"a1", "a2"}

    def test_restore_state(self, tmp_path):
        articles = [
            self._make_digest_article("a1", verdict="vague", resource_loaded=True),
            self._make_digest_article("a2", verdict="follow", resource_loaded=False),
            self._make_digest_article("a3", verdict="ok"),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[])

        from news_recap.recap.tasks.load_resources import LoadResources

        lr = LoadResources(ctx)
        lr.restore_state()

        assert ctx.state["enrich_ids"] == ["a1"]

    def test_high_failure_persists_loaded_before_raise(self, tmp_path):
        """Successful loads are persisted even when failure rate exceeds threshold."""
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod
        from news_recap.recap.tasks.base import RecapPipelineError

        articles = [self._make_digest_article(f"a{i}", verdict="vague") for i in range(10)]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=[f"a{i}" for i in range(10)])

        loaded = {f"a{i}": (f"Title a{i}", "text " * 50) for i in range(5)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            with pytest.raises(RecapPipelineError):
                lr.execute()

        for i in range(5):
            assert ctx.digest.articles[i].resource_loaded is True
        for i in range(5, 10):
            assert ctx.digest.articles[i].verdict == "ok"

    def test_no_url_resets_verdict(self, tmp_path):
        """Articles without URL get verdict reset to 'ok'."""
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="follow"),
        ]
        articles[1].url = ""
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1", "a2"])
        ctx.article_map["a2"] = ArticleIndexEntry(
            source_id="a2", title="Title a2", url="", source="test"
        )

        loaded = {"a1": ("Title a1", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.digest.articles[1].verdict == "ok"
        assert "a2" not in ctx.state["enrich_ids"]
        assert "a1" in ctx.state["enrich_ids"]

    def test_enrich_ids_scoped_to_original(self, tmp_path):
        """enrich_ids must not expand beyond the original set."""
        from unittest.mock import patch

        from news_recap.recap.tasks import load_resources as lr_mod

        articles = [
            self._make_digest_article("a1", verdict="vague"),
            self._make_digest_article("a2", verdict="ok", resource_loaded=True),
        ]
        ctx = self._make_ctx(tmp_path, articles, enrich_ids=["a1"])

        loaded = {"a1": ("Title a1", "text " * 50)}

        with (
            patch.object(lr_mod, "load_resource_texts", return_value=loaded),
            patch.object(lr_mod, "get_run_logger"),
        ):
            from news_recap.recap.tasks.load_resources import LoadResources

            lr = LoadResources(ctx)
            lr.execute()

        assert ctx.state["enrich_ids"] == ["a1"]
        assert "a2" not in ctx.state["enrich_ids"]
