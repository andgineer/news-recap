"""Jev dedup: pair state, star grouping, wider net, and the Deduplicate task's Jev path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec
import pytest
from typesafe_sdk import SystemOneResponse

from news_recap.recap.jev.client import JevUnavailableError
from news_recap.recap.jev.dedup import (
    PAIR_KEY,
    find_duplicates,
    merge_groups,
    pair_key,
    pair_state,
    wide_pairs,
)
from news_recap.recap.exceptions import RecapPipelineError
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import PipelineInput
from news_recap.recap.tasks import deduplicate as dedup_mod
from news_recap.recap.tasks.base import FlowContext
from news_recap.recap.tasks.deduplicate import Deduplicate
from news_recap.recap.tasks.prompts import PromptBackend


def _article(article_id: str, text_len: int = 10, enriched: str | None = None) -> DigestArticle:
    return DigestArticle(
        article_id=article_id,
        title=f"Title {article_id}",
        url=f"https://example.com/{article_id}",
        source=f"src-{article_id}.com",
        published_at="",
        clean_text="x" * text_len,
        enriched_title=enriched,
    )


class _FakeJev:
    """Answers pair requests from ``{frozenset(headlines): probability}`` (default 0)."""

    def __init__(self, probs: dict[frozenset[str], float], error: Exception | None = None):
        self.probs = probs
        self.error = error
        self.model = "jev-1.13.0"
        self.input_tokens = 0
        self.requests = 0
        self.calls: list[list[tuple[dict, dict]]] = []

    def decide(self, requests):
        self.calls.append(list(requests))
        if self.error is not None:
            self.input_tokens += 40
            raise self.error
        out = []
        for state, questions in requests:
            assert list(questions) == [PAIR_KEY]
            key = frozenset((state["article_a"]["headline"], state["article_b"]["headline"]))
            self.input_tokens += 100
            self.requests += 1
            out.append(
                SystemOneResponse.model_validate(
                    {
                        "model": self.model,
                        "usage": {"input_tokens": 100},
                        "answers": {PAIR_KEY: {"type": "noul", "noul": self.probs.get(key, 0.0)}},
                    },
                ),
            )
        return out


def _same(*titles: str, p: float = 0.9) -> dict[frozenset[str], float]:
    return {frozenset(f"Title {t}" for t in titles): p}


def test_pair_state_variants() -> None:
    a, b = _article("a", enriched="Better a"), _article("b")
    assert pair_state(a, b) == {
        "article_a": {"headline": "Better a"},
        "article_b": {"headline": "Title b"},
    }
    lead = pair_state(a, b, "lead")["article_b"]
    assert lead == {"headline": "Title b", "source": "src-b.com", "lead": "x" * 10}
    with pytest.raises(ValueError, match="unknown state variant"):
        pair_state(a, b, "full")


def test_merge_groups_puts_the_longest_text_first_without_chaining() -> None:
    a, b, c = _article("a", 5), _article("b", 50), _article("c", 20)
    same = {pair_key(a, b), pair_key(a, c)}
    groups = merge_groups([a, b, c], lambda x, y: pair_key(x, y) in same)
    assert [[x.article_id for x in g] for g in groups] == [["b", "a"]]


def test_wide_pairs_takes_the_band_outside_candidate_groups() -> None:
    a, b, c, d = (_article(x) for x in "abcd")
    embeddings = {"a": [1.0, 0.0], "b": [0.95, 0.312], "c": [0.88, 0.475], "d": [0.0, 1.0]}
    pairs = wide_pairs([a, b, c, d], embeddings, groups=[[a, b]], high=0.90, low=0.85)
    assert [(x.article_id, y.article_id) for x, y in pairs] == [("a", "c")]
    assert wide_pairs([a, b, c, d], embeddings, groups=[], high=0.96, low=0.85) == [(a, b), (a, c)]


def test_wide_pairs_keeps_the_most_similar_pairs_over_the_limit() -> None:
    a, b, c = (_article(x) for x in "abc")
    embeddings = {"a": [1.0, 0.0], "b": [0.88, 0.475], "c": [0.95, 0.312]}
    pairs = wide_pairs([a, b, c], embeddings, groups=[], high=0.96, low=0.85, limit=1)
    assert pairs == [(a, c)]


def test_find_duplicates_uses_a_stricter_threshold_for_the_wider_net() -> None:
    a, b, c, d, e = (_article(x, n) for x, n in zip("abcde", (50, 40, 30, 20, 10), strict=True))
    client = _FakeJev(
        {
            **_same("a", "b", p=0.45),  # candidate group: >= 0.40 merges
            **_same("c", "d", p=0.6),  # wider net: < 0.70 does not merge
            **_same("a", "e", p=0.75),  # wider net: merges, joins a's group
        },
    )
    merges, answers = find_duplicates(client, [[a, b]], [(c, d), (a, e)])  # type: ignore[arg-type]

    assert [[x.article_id for x in g] for g in merges] == [["a", "b", "e"]]
    assert [(x.a.article_id, x.b.article_id, x.wide, x.same) for x in answers] == [
        ("a", "b", False, True),
        ("c", "d", True, False),
        ("a", "e", True, True),
    ]
    assert client.requests == 3


# ---------------------------------------------------------------------------
# Deduplicate.execute with dedup_backend="jev"
# ---------------------------------------------------------------------------


class _VectorEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text.split(".")[0]] for text in texts]


def _ctx(tmp_path: Path, articles: list[DigestArticle]) -> FlowContext:
    pdir = tmp_path / "pipeline"
    pdir.mkdir()
    inp = MagicMock(spec=PipelineInput)
    inp.dedup_backend = "jev"
    inp.dedup_threshold = 0.90
    inp.dedup_model_name = "intfloat/multilingual-e5-small"
    inp.jev_model = "jev-1.13.0"
    inp.data_dir = str(tmp_path)
    inp.preferences = UserPreferences(language="ru")
    inp.prompt_backend = PromptBackend.CLI
    digest = Digest(
        digest_id="test",
        run_date="2026-10-01",
        status="running",
        pipeline_dir=str(pdir),
        articles=[msgspec.structs.replace(a) for a in articles],
    )
    return FlowContext(pdir=pdir, workdir_mgr=MagicMock(), inp=inp, article_map={}, digest=digest)


_VECTORS = {
    "Title a": [1.0, 0.0],
    "Enriched b": [0.999, 0.045],  # same group as a (similarity >= 0.90)
    "Title c": [0.87, -0.493],  # wider net with a only
    "Title d": [0.0, 1.0],
}


def _articles() -> list[DigestArticle]:
    return [
        _article("a", 50),
        _article("b", 40, enriched="Enriched b"),
        _article("c", 30),
        _article("d", 20),
    ]


class _HeadlineAgent:
    """Stands in for ``run_single_agent``: records prompts, answers with *stdout* or raises."""

    def __init__(self, stdout: str | BaseException) -> None:
        self.stdout = stdout
        self.prompts: list[str] = []

    def __call__(self, ctx: FlowContext, step_name: str, prompt: str, batch: int) -> Path:
        assert step_name == "recap_dedup"
        self.prompts.append(prompt)
        if isinstance(self.stdout, BaseException):
            raise self.stdout
        path = ctx.pdir / f"dedup-{batch}" / "output" / "agent_stdout.log"
        path.parent.mkdir(parents=True)
        path.write_text(self.stdout, "utf-8")
        return path


def test_jev_backend_merges_and_writes_the_headline_in_one_launch(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _articles())
    client = _FakeJev({frozenset({"Title a", "Enriched b"}): 0.9, **_same("a", "c", p=0.8)})
    agent = _HeadlineAgent("GROUP 1: Merged a, b and c\n")
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(_VECTORS)),
        patch.object(dedup_mod, "make_jev_client", return_value=client),
        patch.object(dedup_mod, "run_single_agent", agent),
        patch.object(dedup_mod, "_run_llm_dedup") as llm,
    ):
        Deduplicate(ctx).execute()

    llm.assert_not_called()
    assert len(agent.prompts) == 1
    assert "=== GROUP 1 (3 articles) ===" in agent.prompts[0]
    assert all(t in agent.prompts[0] for t in ("Title a", "Enriched b", "Title c"))
    assert "OUTPUT LANGUAGE: Russian" in agent.prompts[0]
    assert [a.article_id for a in ctx.digest.articles] == ["a", "d"]
    keeper = ctx.digest.articles[0]
    assert keeper.enriched_title == "Merged a, b and c"
    assert [u["url"] for u in keeper.alt_urls] == ["https://example.com/b", "https://example.com/c"]

    task_dir = ctx.pdir / "dedup-jev"
    usage = json.loads((task_dir / "meta" / "usage.json").read_text("utf-8"))
    assert (usage["backend"], usage["requests"], usage["tokens_used"]) == ("jev", 2, 200)
    answers = json.loads((task_dir / "output" / "jev_answers.json").read_text("utf-8"))
    assert [(r["a"], r["b"], r["wide"], r["same"]) for r in answers] == [
        ("a", "b", False, True),
        ("a", "c", True, True),
    ]


def test_failed_headline_launch_leaves_the_groups_unmerged(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [_article("a", 50), _article("b", 40), _article("d", 20)])
    vectors = {**_VECTORS, "Title b": _VECTORS["Enriched b"]}
    client = _FakeJev(_same("a", "b", p=0.9))
    agent = _HeadlineAgent(RecapPipelineError("recap_dedup", "quota"))
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(vectors)),
        patch.object(dedup_mod, "make_jev_client", return_value=client),
        patch.object(dedup_mod, "run_single_agent", agent),
    ):
        Deduplicate(ctx).execute()

    assert len(agent.prompts) == 1
    assert [a.article_id for a in ctx.digest.articles] == ["a", "b", "d"]
    assert all(a.enriched_title is None and not a.alt_urls for a in ctx.digest.articles)


def test_group_left_without_a_headline_stays_unmerged(tmp_path: Path) -> None:
    articles = [_article("a", 50), _article("b", 40, enriched="Enriched b"), _article("c", 30)]
    ctx = _ctx(tmp_path, [*articles, _article("d", 20), _article("e", 10)])
    vectors = {**_VECTORS, "Title e": _VECTORS["Title d"]}
    client = _FakeJev({frozenset({"Title a", "Enriched b"}): 0.9, **_same("d", "e", p=0.9)})
    agent = _HeadlineAgent("GROUP 2: Merged d and e\n")
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(vectors)),
        patch.object(dedup_mod, "make_jev_client", return_value=client),
        patch.object(dedup_mod, "run_single_agent", agent),
    ):
        Deduplicate(ctx).execute()

    titles = {a.article_id: a.enriched_title for a in ctx.digest.articles}
    assert titles == {"a": None, "b": "Enriched b", "c": None, "d": "Merged d and e"}


def test_no_merges_means_no_headline_launch(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _articles())
    agent = _HeadlineAgent("")
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(_VECTORS)),
        patch.object(dedup_mod, "make_jev_client", return_value=_FakeJev({})),
        patch.object(dedup_mod, "run_single_agent", agent),
    ):
        Deduplicate(ctx).execute()

    assert agent.prompts == []
    assert len(ctx.digest.articles) == 4


def test_jev_unavailable_falls_back_to_llm(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _articles())
    client = _FakeJev({}, error=JevUnavailableError("TypeSafeRateLimitError: 429"))
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(_VECTORS)),
        patch.object(dedup_mod, "make_jev_client", return_value=client),
        patch.object(dedup_mod, "_run_llm_dedup", return_value=([], 0)) as llm,
    ):
        Deduplicate(ctx).execute()

    llm.assert_called_once()
    usage = json.loads((ctx.pdir / "dedup-jev" / "meta" / "usage.json").read_text("utf-8"))
    assert usage["tokens_used"] == 40
    assert len(ctx.digest.articles) == 4


def test_jev_backend_without_key_falls_back_to_llm(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _articles())
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(_VECTORS)),
        patch.object(dedup_mod, "make_jev_client", return_value=None),
        patch.object(dedup_mod, "_run_llm_dedup", return_value=([], 0)) as llm,
    ):
        Deduplicate(ctx).execute()
    llm.assert_called_once()
    assert not (ctx.pdir / "dedup-jev").exists()


def test_llm_backend_never_calls_jev(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _articles())
    ctx.inp.dedup_backend = "llm"
    with (
        patch.object(dedup_mod, "build_embedder", return_value=_VectorEmbedder(_VECTORS)),
        patch.object(dedup_mod, "make_jev_client") as make_client,
        patch.object(dedup_mod, "_run_llm_dedup", return_value=([], 0)),
    ):
        Deduplicate(ctx).execute()
    make_client.assert_not_called()
