"""Jev classify: questions, state variants, verdicts, and the Classify task's Jev path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec
import pytest
from typesafe_sdk import SystemOneResponse

from news_recap.recap.contracts import ArticleIndexEntry
from news_recap.recap.jev.classify import (
    LEAD_CHARS,
    article_state,
    classify_articles,
    policy_questions,
)
from news_recap.recap.jev.client import JevUnavailableError
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import PipelineInput
from news_recap.recap.tasks import classify as classify_mod
from news_recap.recap.tasks.base import FlowContext
from news_recap.recap.tasks.classify import Classify

_POLICY = "horoscopes, Croatian domestic news (unless it involves Serbia, Hungary)"


def _article(article_id: str, title: str | None = None) -> DigestArticle:
    return DigestArticle(
        article_id=article_id,
        title=title or f"Title {article_id}",
        url=f"https://example.com/{article_id}",
        source="example.com",
        published_at="2026-10-01T00:00:00+00:00",
        clean_text="x" * (LEAD_CHARS + 50),
    )


def _response(probs: dict[str, float], tokens: int = 100) -> SystemOneResponse:
    return SystemOneResponse.model_validate(
        {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": tokens, "output_tokens": 0},
            "answers": {k: {"type": "noul", "noul": p} for k, p in probs.items()},
        },
    )


class _FakeJev:
    """Answers each request from *probs_by_title*; raises *error* instead when set."""

    def __init__(self, probs_by_title: dict[str, dict[str, float]], error: Exception | None = None):
        self.probs_by_title = probs_by_title
        self.error = error
        self.model = "jev-1.13.0"
        self.input_tokens = 0
        self.requests = 0
        self.calls: list[list[tuple[dict, dict]]] = []

    def decide(self, requests):
        self.calls.append(list(requests))
        if self.error is not None:
            self.input_tokens += 40
            self.requests += 1
            raise self.error
        out = []
        for state, _questions in requests:
            out.append(_response(self.probs_by_title[state["headline"]]))
            self.input_tokens += 100
            self.requests += 1
        return out


def test_policy_questions_name_each_topic() -> None:
    questions = policy_questions(_POLICY)
    assert list(questions) == ["t0", "t1", "vague"]
    assert '"horoscopes"' in questions["t0"].instructions
    assert '"Croatian domestic news (unless it involves Serbia, Hungary)"' in (
        questions["t1"].instructions
    )


def test_policy_questions_empty_policy_asks_only_vague() -> None:
    assert list(policy_questions("")) == ["vague"]


@pytest.mark.parametrize(
    ("variant", "keys"),
    [
        ("full", ["headline", "source", "lead"]),
        ("no_source", ["headline", "lead"]),
        ("headline_only", ["headline"]),
    ],
)
def test_article_state_variants(variant: str, keys: list[str]) -> None:
    state = article_state(_article("a"), variant)
    assert list(state) == keys
    assert state["headline"] == "Title a"
    if "lead" in state:
        assert len(state["lead"]) == LEAD_CHARS


def test_article_state_rejects_unknown_variant() -> None:
    with pytest.raises(ValueError, match="unknown state variant"):
        article_state(_article("a"), "lead_only")


def test_classify_articles_returns_verdict_and_probs_per_article() -> None:
    articles = [_article("a"), _article("b"), _article("c")]
    client = _FakeJev(
        {
            "Title a": {"t0": 0.9, "t1": 0.1, "vague": 0.1},
            "Title b": {"t0": 0.1, "t1": 0.1, "vague": 0.8},
            "Title c": {"t0": 0.1, "t1": 0.2, "vague": 0.2},
        },
    )
    results = classify_articles(client, articles, _POLICY)
    assert {k: v[0] for k, v in results.items()} == {"a": "exclude", "b": "vague", "c": "ok"}
    assert results["b"][1] == {"t0": 0.1, "t1": 0.1, "vague": 0.8}
    (requests,) = client.calls
    assert [state["headline"] for state, _ in requests] == ["Title a", "Title b", "Title c"]
    assert list(requests[0][1]) == ["t0", "t1", "vague"]


# ---------------------------------------------------------------------------
# Classify.execute with classify_backend="jev"
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path, articles: list[DigestArticle]) -> FlowContext:
    pdir = tmp_path / "pipeline"
    pdir.mkdir()
    inp = MagicMock(spec=PipelineInput)
    inp.articles = articles
    inp.preferences = UserPreferences(exclude=_POLICY)
    inp.classify_backend = "jev"
    inp.jev_model = "jev-1.13.0"
    inp.data_dir = str(tmp_path)
    inp.effective_max_parallel.return_value = 3
    digest = Digest(
        digest_id="test",
        run_date="2026-10-01",
        status="running",
        pipeline_dir=str(pdir),
        articles=[msgspec.structs.replace(a) for a in articles],
    )
    return FlowContext(
        pdir=pdir,
        workdir_mgr=MagicMock(),
        inp=inp,
        article_map={
            a.article_id: ArticleIndexEntry(
                source_id=a.article_id, title=a.title, url=a.url, source=a.source
            )
            for a in articles
        },
        digest=digest,
    )


_PROBS = {
    "Title a": {"t0": 0.9, "t1": 0.1, "vague": 0.1},
    "Title b": {"t0": 0.1, "t1": 0.1, "vague": 0.8},
    "Title c": {"t0": 0.1, "t1": 0.2, "vague": 0.2},
}


def test_jev_backend_sets_verdicts_without_llm(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_article("a"), _article("b"), _article("c")])
    client = _FakeJev(_PROBS)
    with (
        patch.object(classify_mod, "make_jev_client", return_value=client),
        patch.object(classify_mod, "submit_and_collect") as llm,
    ):
        Classify(ctx).execute()

    llm.assert_not_called()
    assert [a.article_id for a in ctx.digest.articles] == ["b", "c"]
    assert [a.verdict for a in ctx.digest.articles] == ["vague", "ok"]
    assert ctx.state["enrich_ids"] == ["b"]
    assert [e.source_id for e in ctx.state["kept_entries"]] == ["b", "c"]

    task_dir = ctx.pdir / "classify-jev"
    usage = json.loads((task_dir / "meta" / "usage.json").read_text("utf-8"))
    assert usage["backend"] == "jev"
    assert usage["tokens_used"] == 300
    assert usage["requests"] == 3
    answers = json.loads((task_dir / "output" / "jev_answers.json").read_text("utf-8"))
    assert [(r["article_id"], r["verdict"]) for r in answers] == [
        ("a", "exclude"),
        ("b", "vague"),
        ("c", "ok"),
    ]
    assert answers[0]["p"] == _PROBS["Title a"]


def test_jev_backend_skips_already_classified(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_article("a"), _article("b"), _article("c")])
    ctx.digest.articles[0].verdict = "ok"
    client = _FakeJev(_PROBS)
    with patch.object(classify_mod, "make_jev_client", return_value=client):
        Classify(ctx).execute()
    (requests,) = client.calls
    assert [state["headline"] for state, _ in requests] == ["Title b", "Title c"]
    assert [a.article_id for a in ctx.digest.articles] == ["a", "b", "c"]


def test_jev_unavailable_falls_back_to_llm(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_article("a"), _article("b")])
    client = _FakeJev(_PROBS, error=JevUnavailableError("TypeSafeRateLimitError: 429"))
    with (
        patch.object(classify_mod, "make_jev_client", return_value=client),
        patch.object(classify_mod, "submit_and_collect", return_value=(0, 0, 0)) as llm,
    ):
        Classify(ctx).execute()

    llm.assert_called_once()
    usage = json.loads((ctx.pdir / "classify-jev" / "meta" / "usage.json").read_text("utf-8"))
    assert usage["tokens_used"] == 40
    assert not (ctx.pdir / "classify-jev" / "output").exists()


def test_jev_backend_without_key_falls_back_to_llm(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_article("a")])
    with (
        patch.object(classify_mod, "make_jev_client", return_value=None),
        patch.object(classify_mod, "submit_and_collect", return_value=(0, 0, 0)) as llm,
    ):
        Classify(ctx).execute()
    llm.assert_called_once()
    assert not (ctx.pdir / "classify-jev").exists()


def test_llm_backend_never_calls_jev(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_article("a")])
    ctx.inp.classify_backend = "llm"
    with (
        patch.object(classify_mod, "make_jev_client") as make_client,
        patch.object(classify_mod, "submit_and_collect", return_value=(0, 0, 0)),
    ):
        Classify(ctx).execute()
    make_client.assert_not_called()
