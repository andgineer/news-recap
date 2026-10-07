"""Tests for scripts/bench_jev.py."""

from __future__ import annotations

import importlib.util
import json
import random
import re
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bench_jev.py"
_SPEC = importlib.util.spec_from_file_location("bench_jev", _PATH)
assert _SPEC and _SPEC.loader
bench_jev = importlib.util.module_from_spec(_SPEC)
sys.modules["bench_jev"] = bench_jev
_SPEC.loader.exec_module(bench_jev)

Item = bench_jev.Item
POLICY = "horoscopes, sports (except Russia)"


def _write_pipeline(root: Path, name: str, titles: list[str], status: str = "completed") -> Path:
    pdir = root / name
    pdir.mkdir(parents=True)
    articles = [
        {"title": t, "source": f"src{i}.com", "clean_text": f"text  of\n{t} " * 50}
        for i, t in enumerate(titles)
    ]
    (pdir / "pipeline_input.json").write_text(
        json.dumps({"articles": articles, "preferences": {"exclude": POLICY}}),
        "utf-8",
    )
    (pdir / "digest.json").write_text(json.dumps({"status": status}), "utf-8")
    return pdir


def _bench(tmp_path: Path) -> bench_jev.Bench:
    return bench_jev.Bench(root=tmp_path / "bench", workdir_root=tmp_path / "workdir")


# --- snapshot ---------------------------------------------------------------


def test_snapshot_copies_new_and_refreshes_incomplete(tmp_path):
    bench = _bench(tmp_path)
    _write_pipeline(bench.workdir_root, "pipeline-a", ["A"])
    _write_pipeline(bench.workdir_root, "pipeline-b", ["B"], status="running")
    (bench.workdir_root / "digests.json").write_text("{}", "utf-8")

    assert bench_jev.snapshot(bench.workdir_root, bench.pipelines) == ["pipeline-a", "pipeline-b"]

    (bench.workdir_root / "pipeline-a" / "extra").write_text("x", "utf-8")
    (bench.workdir_root / "pipeline-b" / "digest.json").write_text(
        '{"status": "completed"}',
        "utf-8",
    )
    assert bench_jev.snapshot(bench.workdir_root, bench.pipelines) == ["pipeline-b"]
    assert not (bench.pipelines / "pipeline-a" / "extra").exists()
    assert bench_jev._digest_completed(bench.pipelines / "pipeline-b")
    assert bench_jev.snapshot(bench.workdir_root, bench.pipelines) == []
    assert sorted(p.name for p in bench.pipelines.iterdir()) == ["pipeline-a", "pipeline-b"]


# --- items ------------------------------------------------------------------


def test_describe_shows_source_lead_and_policy(tmp_path):
    _write_pipeline(tmp_path, "p1", ["Headline"])
    view = bench_jev.describe(tmp_path, Item("p1", "Headline"))
    assert view.source == "src0.com"
    assert view.policy == POLICY
    assert len(view.lead) <= bench_jev.LEAD_CHARS
    assert "\n" not in view.lead
    assert "  " not in view.lead
    with pytest.raises(KeyError):
        bench_jev.describe(tmp_path, Item("p1", "missing"))


def _exp_row(pipeline: str, headline: str, gemini: str, *, excl: float, vague: float) -> dict:
    return {
        "batch": f"{pipeline}/classify-1",
        "headline": f" {headline} ",
        "llm": gemini,
        "p": {"t0": excl, "t1": 0.0, "vague": vague},
    }


def test_stage1_items_takes_all_disagreements_and_seeded_agreements(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_jev, "STAGE1_AGREEMENTS", 3)
    rows = [
        _exp_row("p1", "d-excl", "ok", excl=0.6, vague=0.0),
        _exp_row("p1", "d-vague", "ok", excl=0.0, vague=0.7),
        _exp_row("p1", "d-ok", "exclude", excl=0.59, vague=0.69),
        _exp_row("p1", "d-ok", "exclude", excl=0.59, vague=0.69),
    ]
    rows += [_exp_row("p2", f"a{i}", "ok", excl=0.1, vague=0.1) for i in range(10)]
    path = tmp_path / "exp.json"
    path.write_text(json.dumps({"topics": ["x", "y"], "rows": rows}), "utf-8")

    items = bench_jev.stage1_items(path)

    assert items[:3] == [Item("p1", "d-excl"), Item("p1", "d-vague"), Item("p1", "d-ok")]
    assert len(items) == 6
    assert {i.pipeline for i in items[3:]} == {"p2"}
    assert bench_jev.stage1_items(path) == items


# --- label ------------------------------------------------------------------


def _label(items, path, keys, *, seed=0):
    shown: list[str] = []
    key_iter = iter(keys)

    def read_key():
        try:
            return next(key_iter)
        except StopIteration:
            raise KeyboardInterrupt from None

    remaining = bench_jev.label_items(
        items,
        path,
        lambda item: bench_jev.ItemView(item.headline, "", "", POLICY),
        read_key=read_key,
        show=lambda view, _pos, _total: shown.append(view.headline),
        rng=random.Random(seed),
    )
    return remaining, shown


def test_label_records_undo_and_resumes(tmp_path):
    path = tmp_path / "labels.jsonl"
    items = [Item("p", h) for h in ("a", "b", "c", "d")]

    remaining, shown = _label(items, path, ["o", "?", "x", "u", "v", "s", "q"])

    assert remaining == 1
    assert shown[2] == shown[1]  # an unknown key re-shows the same item
    assert shown[4] == shown[1]  # undo re-shows the undone item
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert [r["label"] for r in rows] == ["ok", "vague", "skip"]
    assert set(rows[0]) == {"pipeline", "headline", "label", "labeler", "labeled_at"}
    assert rows[0]["labeler"] == "user"

    remaining, shown = _label(items, path, ["x"], seed=1)
    assert remaining == 0
    assert len(shown) == 1
    assert set(bench_jev.read_labels(path)) == set(items)


def test_label_undo_with_empty_session_does_nothing(tmp_path):
    path = tmp_path / "labels.jsonl"
    bench_jev.append_label(path, Item("p", "old"), "ok")
    remaining, _ = _label([Item("p", "old"), Item("p", "new")], path, ["u", "q"])
    assert remaining == 1
    assert bench_jev.read_labels(path) == {Item("p", "old"): "ok"}


def test_drop_last_label_refuses_another_item(tmp_path):
    path = tmp_path / "labels.jsonl"
    bench_jev.append_label(path, Item("p", "a"), "ok")
    with pytest.raises(RuntimeError):
        bench_jev.drop_last_label(path, Item("p", "b"))


# --- judge ------------------------------------------------------------------


def test_parse_answers_tolerates_formatting():
    text = "Here you go:\n1: ok\n 2. VAGUE\n3) exclude\n4: unsure\n"
    assert bench_jev.parse_answers(text, 4, bench_jev.VERDICTS) == {
        1: "ok",
        2: "vague",
        3: "exclude",
    }


def test_classify_prompts_batch_and_number_items(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_jev, "JUDGE_BATCH", 2)
    _write_pipeline(tmp_path, "p1", ["A", "B", "C"])
    items = [Item("p1", t) for t in ("A", "B", "C")]

    prompts = bench_jev.classify_prompts(tmp_path, items)

    assert [batch for batch, _ in prompts] == [items[:2], items[2:]]
    assert POLICY in prompts[0][1]
    assert "1. headline: A" in prompts[0][1]
    assert "2. headline: B" in prompts[0][1]
    assert "1. headline: C" in prompts[1][1]
    assert "exactly 1 lines" in prompts[1][1]


def test_judge_classify_caches_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_jev, "JUDGE_BATCH", 2)
    bench = _bench(tmp_path)
    _write_pipeline(bench.pipelines, "p1", ["A", "B", "C"])
    items = [Item("p1", t) for t in ("A", "B", "C")]
    calls: list[Path] = []

    def fake_run(run_dir: Path, model: str) -> str:
        calls.append(run_dir)
        prompt = (run_dir / "prompt.txt").read_text("utf-8")
        heads = re.findall(r"^(\d+)\. headline: (.+)$", prompt, re.M)
        return "\n".join(f"{n}: exclude" for n, headline in heads if headline != "B")

    answers = bench_jev.judge_classify(bench, items, model="m", workers=2, run=fake_run)
    assert answers == {items[0]: "exclude", items[2]: "exclude"}
    assert len(calls) == 2

    calls.clear()
    answers = bench_jev.judge_classify(bench, items, model="m", workers=2, run=fake_run)
    assert len(calls) == 1  # only the unanswered item is retried
    assert items[1] not in answers

    calls.clear()
    bench_jev.judge_classify(bench, items, model="other", workers=2, run=fake_run)
    assert len(calls) == 2  # another model does not reuse cached answers


def test_agreement_report_calibration(monkeypatch):
    monkeypatch.setattr(bench_jev, "CALIBRATION_MIN_ITEMS", 10)
    items = [Item("p", str(i)) for i in range(10)]
    labels = dict.fromkeys(items, "ok")
    answers = dict.fromkeys(items, "ok")

    assert bench_jev.agreement_report(labels, answers, bench_jev.VERDICTS)[-1].startswith(
        "calibrated: yes",
    )
    answers[items[0]] = "vague"
    report = bench_jev.agreement_report(labels, answers, bench_jev.VERDICTS)
    assert report[0] == "judge answered 10 of 10 labelled items; agrees on 9 (90.0%)"
    assert report[-1].startswith("calibrated: yes")
    answers[items[1]] = "exclude"
    report = bench_jev.agreement_report(labels, answers, bench_jev.VERDICTS)
    assert report[-1].startswith("calibrated: no")
    assert report[3].split() == ["ok", "8", "1", "1"]


# --- classify ---------------------------------------------------------------


def _write_classify_task(pdir: Path, num: int, headlines: list[str], stdout: str) -> None:
    task = pdir / f"classify-{num}"
    (task / "input").mkdir(parents=True)
    (task / "output").mkdir(parents=True)
    lines = "\n".join(f"{i}: {h}" for i, h in enumerate(headlines, 1))
    (task / "input" / "task_prompt.txt").write_text(
        f"EDITORIAL POLICY — EXCLUDE:\n{POLICY}\n\n=== HEADLINES (format: NUMBER: HEADLINE) ===\n"
        f"Do NOT write any files.\n{lines}",
        "utf-8",
    )
    (task / "output" / "agent_stdout.log").write_text(stdout, "utf-8")


def test_replay_nights_joins_prompt_and_stdout(tmp_path):
    pdir = _write_pipeline(tmp_path, "p1", ["A", "B", "C", "D"])
    _write_classify_task(pdir, 1, ["A", "B", "Gone"], "1: ok\n2: exclude\n3: vague\n")
    _write_classify_task(pdir, 2, ["C", "D", "A"], "1: vague\n3: exclude\nnoise\n")
    (pdir / "classify-jev").mkdir()

    assert bench_jev.replay_nights(tmp_path, ["p1"]) == {
        Item("p1", "A"): "ok",
        Item("p1", "B"): "exclude",
        Item("p1", "C"): "vague",
    }


class _FakeJevClient:
    model = "jev-1.13.0"

    def __init__(self, probs_by_headline: dict[str, dict[str, float]]) -> None:
        self.probs_by_headline = probs_by_headline
        self.input_tokens = 0
        self.requests = 0
        self.headlines: list[str] = []

    def decide(self, requests):
        from typesafe_sdk import SystemOneResponse

        out = []
        for state, questions in requests:
            assert list(questions) == ["t0", "t1", "vague"]
            self.headlines.append(state["headline"])
            self.input_tokens += 10
            self.requests += 1
            out.append(
                SystemOneResponse.model_validate(
                    {
                        "model": self.model,
                        "usage": {"input_tokens": 10},
                        "answers": {
                            k: {"type": "noul", "noul": p}
                            for k, p in self.probs_by_headline[state["headline"]].items()
                        },
                    },
                ),
            )
        return out


def test_run_classify_variant_only_asks_for_new_items(tmp_path):
    bench = _bench(tmp_path)
    _write_pipeline(bench.pipelines, "p1", ["A", "B"])
    _write_pipeline(bench.pipelines, "p2", ["C"])
    probs = {h: {"t0": 0.1, "t1": 0.2, "vague": 0.3} for h in "ABC"}
    client = _FakeJevClient(probs)

    got = bench_jev.run_classify_variant(bench, client, [Item("p1", "A")], "no_source")
    assert got == {Item("p1", "A"): probs["A"]}

    items = [Item("p1", "A"), Item("p1", "B"), Item("p2", "C")]
    got = bench_jev.run_classify_variant(bench, client, items, "no_source")
    assert client.headlines == ["A", "B", "C"]
    assert set(got) == set(items)
    assert bench_jev.night_tokens(bench, ["no_source"], client.model) == {"p1": 20, "p2": 10}
    assert bench_jev.stored_classify_probs(bench, "no_source", "jev-other") == {}
    assert bench_jev.stored_classify_probs(bench, "full", client.model) == {}


def _night(rows: list[tuple[str, str, float, float, float]]):
    """(headline, gemini, exclude p, vague p in "full", vague p in "headline_only") rows."""
    gemini, full, headline_only = {}, {}, {}
    for headline, gem, excl, vague_full, vague_head in rows:
        item = Item("p", headline)
        gemini[item] = gem
        full[item] = {"t0": excl, "vague": vague_full}
        headline_only[item] = {"t0": 0.0, "vague": vague_head}
    return gemini, {"full": full, "headline_only": headline_only}


def test_evaluate_scores_against_labels_and_agreements():
    gemini, probs = _night(
        [
            ("excl-both", "exclude", 0.9, 0.0, 0.0),
            ("excl-jev-wrong", "ok", 0.8, 0.0, 0.0),
            ("excl-gem-missed", "ok", 0.9, 0.0, 0.0),
            ("vague-jev", "ok", 0.1, 0.8, 0.0),
            ("ok-both", "ok", 0.1, 0.1, 0.1),
            ("unlabelled", "vague", 0.1, 0.1, 0.1),
        ],
    )
    labels = {
        Item("p", "excl-jev-wrong"): "ok",
        Item("p", "excl-gem-missed"): "exclude",
        Item("p", "vague-jev"): "vague",
        Item("p", "ok-both"): "vague",
    }
    config = bench_jev.ClassifyConfig("full", 0.75, "full", 0.65)

    result = bench_jev.evaluate(config, probs, gemini, labels)

    assert result.unknown == (Item("p", "unlabelled"),)
    assert result.jev.total == result.gemini.total == 5
    assert (result.jev.wrong_excludes, result.jev.missed_excludes) == (1, 0)
    assert (result.gemini.wrong_excludes, result.gemini.missed_excludes) == (0, 1)
    assert result.jev.correct("vague") == 1
    assert result.jev.recall("vague") == 0.5
    assert result.gemini.f1("vague") == 0.0
    assert not result.exclude_ok  # Jev's one wrong exclude is more than Gemini's none

    stricter = bench_jev.evaluate(
        bench_jev.ClassifyConfig("full", 0.85, "full", 0.65), probs, gemini, labels
    )
    assert (stricter.jev.wrong_excludes, stricter.jev.missed_excludes) == (0, 0)
    assert stricter.exclude_ok
    assert stricter.vague_ok

    mixed = bench_jev.evaluate(
        bench_jev.ClassifyConfig("full", 0.85, "headline_only", 0.65), probs, gemini, labels
    )
    assert mixed.jev.correct("vague") == 0


def test_classify_report_gate():
    gemini, probs = _night(
        [
            ("excl", "ok", 0.9, 0.0, 0.0),
            ("vague", "vague", 0.1, 0.9, 0.0),
            ("ok", "ok", 0.1, 0.1, 0.0),
        ],
    )
    labels = {Item("p", "excl"): "exclude"}
    result = bench_jev.evaluate(bench_jev.PRODUCTION_CONFIG, probs, gemini, labels)

    passed, lines = bench_jev.classify_report(result, cost_per_month=0.5)
    assert passed
    assert "wrong excludes: Jev 0, Gemini 0; missed excludes: Jev 0, Gemini 1" in lines
    assert not bench_jev.classify_report(result, cost_per_month=1.5)[0]

    gemini[Item("p", "new")] = "vague"
    probs["full"][Item("p", "new")] = {"t0": 0.1, "vague": 0.1}
    incomplete = bench_jev.evaluate(bench_jev.PRODUCTION_CONFIG, probs, gemini, labels)
    passed, lines = bench_jev.classify_report(incomplete, cost_per_month=0.5)
    assert not passed
    assert lines[-1] == "gate incomplete: label 1 disagreements first"


def test_sweep_ranks_exclude_gate_first(monkeypatch):
    monkeypatch.setattr(bench_jev, "EXCLUDE_GRID", (0.5, 0.9))
    monkeypatch.setattr(bench_jev, "VAGUE_GRID", (0.5,))
    gemini, probs = _night(
        [
            ("borderline", "ok", 0.6, 0.0, 0.0),
            ("excl", "exclude", 0.95, 0.0, 0.0),
        ],
    )
    del probs["headline_only"]
    results = bench_jev.sweep(probs, gemini, {Item("p", "borderline"): "ok"})
    assert [str(r.config) for r in results] == ["full:0.90:full:0.50", "full:0.50:full:0.50"]
    assert results[0].exclude_ok and not results[1].exclude_ok


def test_classify_config_parse_rejects_unknown_variant():
    with pytest.raises(ValueError, match="variants"):
        bench_jev.ClassifyConfig.parse("lead:0.7:full:0.6")
    assert bench_jev.ClassifyConfig.parse("full:0.7:full:0.6").variants == ("full",)


def test_monthly_cost_uses_median_night():
    cost, lines = bench_jev.monthly_cost({"a": 100_000, "b": 400_000, "c": 900_000})
    assert cost == pytest.approx(400_000 * 30 * 0.042 / 1_000_000)
    assert "median 400,000, max 900,000 (3 nights)" in lines[0]


def test_write_pending_dedupes_and_replaces(tmp_path):
    path = tmp_path / "pending.jsonl"
    items = [Item("p", "b"), Item("p", "a"), Item("p", "b")]
    assert bench_jev.write_pending(path, items) == 2
    assert bench_jev.read_items(path) == [Item("p", "a"), Item("p", "b")]
    assert bench_jev.write_pending(path, []) == 0
    assert bench_jev.read_items(path) == []


# --- route ------------------------------------------------------------------


def _route_article(article_id: str, enriched_title: str | None = None):
    return bench_jev.DigestArticle(
        article_id=article_id,
        title=f"Title {article_id}",
        url=f"https://example.rs/srbija/politika/{article_id}",
        source="example.rs",
        published_at="2026-10-01T00:00:00+00:00",
        clean_text="lead " * 100,
        enriched_title=enriched_title,
    )


def test_default_sections_parse_into_six_described_sections() -> None:
    sections = bench_jev.build_sections("Russia, Serbia, war in Ukraine")
    assert [s.name for s in sections if s.follow] == ["Russia", "Serbia", "war in Ukraine"]
    general = [s for s in sections if not s.follow]
    assert len(general) == 6
    assert general[0].name == "International politics and security"
    assert general[0].criterion.startswith("International politics and security: diplomacy, ")
    assert [s.key for s in sections] == [f"s{i}" for i in range(1, 10)]


def test_route_questions_ask_follow_topics_separately() -> None:
    sections = bench_jev.build_sections("Serbia (including Vojvodina)", "Economy, Science (space)")
    questions = bench_jev.route_questions(sections)

    assert list(questions) == ["s1", bench_jev.CHOICE_KEY]
    follow = questions["s1"]
    assert isinstance(follow, bench_jev.Noul)
    assert '"Serbia: including Vojvodina"' in str(follow.instructions)
    choice = questions[bench_jev.CHOICE_KEY]
    assert isinstance(choice, bench_jev.Choice)
    assert list(choice.criteria) == ["s2", "s3", bench_jev.OTHER]
    assert (choice.criteria["s2"], choice.criteria["s3"]) == ("Economy", "Science: space")


def test_pick_section_prefers_the_most_probable_follow_topic() -> None:
    probs = {"s1": 0.5, "s2": 0.8, "s3": 0.95, bench_jev.OTHER: 0.05}
    assert bench_jev.pick_section(probs, ["s1", "s2"], follow_threshold=0.3) == "s2"
    assert bench_jev.pick_section(probs, ["s1", "s2"], follow_threshold=0.9) == "s3"
    assert bench_jev.pick_section(probs, [], follow_threshold=0.3) == "s3"


def test_pick_section_sends_low_confidence_to_other() -> None:
    probs = {"s1": 0.1, "s2": 0.35, "s3": 0.33, bench_jev.OTHER: 0.32}
    assert (
        bench_jev.pick_section(probs, ["s1"], follow_threshold=0.3, min_confidence=0.4)
        == bench_jev.OTHER
    )
    assert bench_jev.pick_section(probs, ["s1"], follow_threshold=0.3, min_confidence=0.3) == "s2"


def test_route_state_uses_enriched_title_and_url() -> None:
    state = bench_jev.route_state(_route_article("a", enriched_title="Better headline"))
    assert state["headline"] == "Better headline"
    assert state["url"] == "https://example.rs/srbija/politika/a"
    assert state["source"] == "example.rs"
    assert "url" not in bench_jev.route_state(_route_article("a"), "lead")
    assert bench_jev.route_state(_route_article("a"), "lead")["headline"] == "Title a"
    with pytest.raises(ValueError, match="unknown state variant"):
        bench_jev.route_state(_route_article("a"), "headline_only")


_ROUTE_SECTIONS = "Economy, Science"


def _write_route_night(root: Path, name: str = "p") -> Path:
    """Articles A-F; today's blocks: [A, B] in "Сербия", [C] and [D, E] elsewhere; F unplaced."""
    pdir = root / name
    pdir.mkdir(parents=True)
    articles = [
        {
            "article_id": f"id-{t}",
            "title": t,
            "url": f"https://news.rs/{t}",
            "source": "news.rs",
            "published_at": "",
            "clean_text": f"lead  of\n{t} " * 40,
            "verdict": "ok",
        }
        for t in "ABCDEF"
    ]
    blocks = [
        {"title": "b0", "article_ids": ["id-A", "id-B"]},
        {"title": "b1", "article_ids": ["id-C"]},
        {"title": "b2", "article_ids": ["id-D", "id-E"]},
    ]
    recaps = [
        {"title": "Сербия", "block_indices": [0]},
        {"title": "Технологии", "block_indices": [1, 2]},
    ]
    (pdir / "digest.json").write_text(
        json.dumps(
            {"status": "completed", "articles": articles, "blocks": blocks, "recaps": recaps},
        ),
        "utf-8",
    )
    (pdir / "pipeline_input.json").write_text(
        json.dumps({"articles": articles, "preferences": {"follow": "Serbia", "exclude": POLICY}}),
        "utf-8",
    )
    return pdir


def _route_night(tmp_path: Path, sections: str = _ROUTE_SECTIONS):
    return bench_jev.load_route_night(_write_route_night(tmp_path), sections)


class _FakeRouteClient:
    """Serbia yes-probability and general-section probabilities per headline."""

    model = "jev-1.13.0"

    def __init__(self, probs_by_headline: dict[str, tuple[float, dict[str, float]]]) -> None:
        self.probs_by_headline = probs_by_headline
        self.input_tokens = 0
        self.requests = 0
        self.headlines: list[str] = []

    def decide(self, requests):
        from typesafe_sdk import SystemOneResponse

        out = []
        for state, questions in requests:
            assert list(questions) == ["s1", "section"]
            self.headlines.append(state["headline"])
            assert state["url"].startswith("https://news.rs/")
            serbia, general = self.probs_by_headline[state["headline"]]
            self.input_tokens += 10
            self.requests += 1
            choice = max(general, key=general.__getitem__)
            answers = {
                "s1": {"type": "noul", "noul": serbia},
                "section": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": general[choice],
                    "probabilities": general,
                },
            }
            out.append(
                SystemOneResponse.model_validate(
                    {"model": self.model, "usage": {"input_tokens": 10}, "answers": answers},
                ),
            )
        return out


_ECONOMY = {"s2": 0.9, "s3": 0.1, "other": 0.0}
_SCIENCE = {"s2": 0.1, "s3": 0.9, "other": 0.0}
_UNSURE = {"s2": 0.3, "s3": 0.3, "other": 0.4}


def test_load_route_night_maps_llm_follow_sections_and_multi_article_blocks(tmp_path):
    night = _route_night(tmp_path)

    assert night.follow_names == ("Serbia",)
    assert [s.name for s in night.sections] == ["Serbia", "Economy", "Science"]
    assert {i.headline: f for i, f in night.llm_follow.items()} == {
        "A": "Serbia",
        "B": "Serbia",
        "C": "none",
        "D": "none",
        "E": "none",
    }
    assert [[i.headline for i in b] for b in night.blocks] == [["A", "B"], ["D", "E"]]
    assert len(night.articles) == 6


def test_run_route_asks_only_for_unstored_items_of_the_same_question(tmp_path):
    bench = _bench(tmp_path)
    night = _route_night(bench.pipelines)
    client = _FakeRouteClient({h: (0.1, _ECONOMY) for h in "ABCDEF"})

    probs, tokens = bench_jev.run_route(bench, client, [night], "url")
    assert client.headlines == list("ABCDEF")
    assert probs[Item("p", "A")] == {"s1": 0.1, **_ECONOMY}
    assert tokens == {"p": 60}

    bench_jev.run_route(bench, client, [night], "url")
    assert client.requests == 6

    reworded = bench_jev.load_route_night(bench.pipelines / "p", "Economy, Science (space)")
    bench_jev.run_route(bench, client, [reworded], "url")
    assert client.requests == 12
    with pytest.raises(SystemExit, match="incomplete"):
        bench_jev.run_route(bench, None, [night], "lead")


def _route_probs(**by_headline: tuple[float, dict[str, float]]) -> dict:
    return {Item("p", h): {"s1": serbia, **general} for h, (serbia, general) in by_headline.items()}


def test_evaluate_route_measures_splits_other_and_follow_disagreements(tmp_path):
    night = _route_night(tmp_path)
    probs = _route_probs(
        A=(0.9, _ECONOMY),
        B=(0.1, _ECONOMY),
        C=(0.1, _UNSURE),
        D=(0.1, _SCIENCE),
        E=(0.1, _SCIENCE),
        F=(0.8, _SCIENCE),
    )
    labels = {Item("p", "B"): frozenset({"Serbia"})}

    result = bench_jev.evaluate_route(bench_jev.RouteConfig(0.5, 0.4), [night], probs, labels)

    assert result.sections[Item("p", "A")] == "Serbia"
    assert result.sections[Item("p", "B")] == "Economy"
    assert result.sections[Item("p", "C")] == "other"
    assert result.sections[Item("p", "F")] == "Serbia"
    assert (result.split_blocks, result.split_rate) == (1, 0.5)
    assert result.other_share == pytest.approx(1 / 6)
    assert result.disagreements == (Item("p", "B"),)
    assert (result.right(result.jev_follow), result.right(result.llm_follow)) == (0, 1)
    assert not result.follow_ok
    assert not result.structure_ok

    lenient = bench_jev.evaluate_route(bench_jev.RouteConfig(0.05, 0.3), [night], probs, {})
    assert lenient.split_blocks == 0  # every article clears the follow threshold
    assert lenient.unknown == (Item("p", "C"), Item("p", "D"), Item("p", "E"))


def test_route_report_gate(tmp_path):
    night = _route_night(tmp_path)
    probs = _route_probs(
        A=(0.9, _ECONOMY),
        B=(0.9, _ECONOMY),
        C=(0.1, _ECONOMY),
        D=(0.9, _SCIENCE),
        E=(0.1, _SCIENCE),
        F=(0.1, _SCIENCE),
    )
    config = bench_jev.RouteConfig(0.5, 0.4)

    result = bench_jev.evaluate_route(config, [night], probs, {})
    passed, lines = bench_jev.route_report(result, [night])
    assert not passed
    assert lines[-1] == "gate incomplete: label 1 follow disagreements first"
    assert "split: 1 of 2 multi-article blocks (50.0%)" in lines

    probs[Item("p", "D")] = {"s1": 0.1, **_SCIENCE}
    result = bench_jev.evaluate_route(config, [night], probs, {})
    passed, lines = bench_jev.route_report(result, [night])
    assert passed
    assert "gate follow: PASS (Jev right 0 >= LLM right 0)" in lines
    assert any(line.startswith("  Serbia") and "LLM->Jev 2/2" in line for line in lines)


def test_read_route_labels_accepts_several_placements(tmp_path):
    path = tmp_path / "route.jsonl"
    bench_jev._append_jsonl(
        path,
        [
            {"pipeline": "p", "headline": "a", "label": ["Serbia"]},
            {"pipeline": "p", "headline": "a", "label": ["Serbia", "none"]},
            {"pipeline": "p", "headline": "b", "label": "skip"},
        ],
    )
    assert bench_jev.read_route_labels(path) == {Item("p", "a"): frozenset({"Serbia", "none"})}


def test_write_route_pending_hides_both_answers(tmp_path):
    night = _route_night(tmp_path)
    path = tmp_path / "pending.jsonl"

    assert bench_jev.write_route_pending(path, [night], [Item("p", "B")]) == 1
    (row,) = bench_jev._read_jsonl(path)
    assert set(row) == {"pipeline", "headline", "enriched_title", "source", "lead"}
    assert row["lead"].startswith("lead of B lead of B")


# --- dedup ------------------------------------------------------------------

_SINGLE_PROMPT = """You are a senior news editor.
=== NEWS (3 total) ===
Do NOT write any files.
1: [a.com] Alpha
2: [b.com] Beta
3: [c.com] Gamma"""

_MULTI_PROMPT = """Groups below.
=== CLUSTER 1 (2 articles) ===
1: [a.com] Delta
2: [b.com] Epsilon

=== CLUSTER 2 (2 articles) ===
1: [c.com] Zeta
2: [d.com] Eta
"""


def test_parse_dedup_task_single_and_multi_cluster():
    single = bench_jev.parse_dedup_task(_SINGLE_PROMPT, "MERGED: x\n1, 3\nSINGLE: 2\n")
    assert single == [([("a.com", "Alpha"), ("b.com", "Beta"), ("c.com", "Gamma")], [[0, 2]])]

    multi = bench_jev.parse_dedup_task(
        _MULTI_PROMPT, "CLUSTER 1:\nSINGLE: 1\nSINGLE: 2\n\nCLUSTER 2:\nMERGED: y\n1, 2\n"
    )
    assert [m for _, m in multi] == [[], [[0, 1]]]
    assert multi[1][0] == [("c.com", "Zeta"), ("d.com", "Eta")]

    rejected = bench_jev.parse_dedup_task(_MULTI_PROMPT, "CLUSTER 2:\nMERGED: y\n1, 2\n")
    assert [m for _, m in rejected] == [[], []]


def _write_dedup_night(root: Path, name: str = "p") -> Path:
    pdir = _write_pipeline(root, name, ["Alpha", "Beta", "Gamma", "Delta"])
    task = pdir / "dedup-1"
    (task / "input").mkdir(parents=True)
    (task / "output").mkdir()
    (task / "input" / "task_prompt.txt").write_text(_SINGLE_PROMPT, "utf-8")
    (task / "output" / "agent_stdout.log").write_text(
        "MERGED: x\n1, 2\nSINGLE: 3\n",
        "utf-8",
    )
    (pdir / "dedup-jev").mkdir()
    return pdir


def test_replay_dedup_reads_clusters_with_article_text(tmp_path):
    (cluster,) = bench_jev.replay_dedup(_write_dedup_night(tmp_path))
    assert [a.title for a in cluster.articles] == ["Alpha", "Beta", "Gamma"]
    assert cluster.articles[0].clean_text.startswith("text  of\nAlpha")
    assert cluster.gemini_pairs() == {("p", "Alpha", "Beta")}
    assert len(cluster.pairs()) == 3


class _FakePairClient:
    model = "jev-1.13.0"

    def __init__(self, probs: dict[frozenset[str], float]) -> None:
        self.probs = probs
        self.input_tokens = 0
        self.requests = 0

    def decide(self, requests):
        from typesafe_sdk import SystemOneResponse

        out = []
        for state, _ in requests:
            key = frozenset((state["article_a"]["headline"], state["article_b"]["headline"]))
            self.requests += 1
            self.input_tokens += 7
            out.append(
                SystemOneResponse.model_validate(
                    {
                        "model": self.model,
                        "usage": {"input_tokens": 7},
                        "answers": {"same": {"type": "noul", "noul": self.probs.get(key, 0.1)}},
                    },
                ),
            )
        return out


def test_run_dedup_variant_stores_per_question(tmp_path):
    bench = _bench(tmp_path)
    clusters = bench_jev.replay_dedup(_write_dedup_night(bench.pipelines))
    client = _FakePairClient({frozenset({"Alpha", "Beta"}): 0.9})

    probs = bench_jev.run_dedup_variant(bench, client, clusters, "headline", "news")
    assert probs[("p", "Alpha", "Beta")] == (0.9, 7)
    assert client.requests == 3
    bench_jev.run_dedup_variant(bench, client, clusters, "headline", "news")
    assert client.requests == 3
    bench_jev.run_dedup_variant(bench, client, clusters, "headline", "event")
    assert client.requests == 6
    with pytest.raises(SystemExit, match="incomplete"):
        bench_jev.run_dedup_variant(bench, None, clusters, "lead", "news")


def test_evaluate_dedup_gate_counts_wrong_and_missed_merges(tmp_path):
    (cluster,) = bench_jev.replay_dedup(_write_dedup_night(tmp_path))
    ab, ac, bc = ("p", "Alpha", "Beta"), ("p", "Alpha", "Gamma"), ("p", "Beta", "Gamma")
    probs = {ab: (0.2, 5), ac: (0.9, 5), bc: (0.1, 5)}
    config = bench_jev.DedupConfig("headline", "news", 0.5)

    unknown = bench_jev.evaluate_dedup(config, [cluster], probs, {})
    assert unknown.unknown == (ab, ac)
    passed, lines = bench_jev.dedup_report(unknown)
    assert not passed
    assert lines[-1] == "gate incomplete: label 2 disputed pairs first"

    result = bench_jev.evaluate_dedup(config, [cluster], probs, {ab: "different", ac: "same"})
    assert (result.jev.wrong_merges, result.jev.missed_merges, result.jev.correct) == (0, 0, 3)
    assert (result.gemini.wrong_merges, result.gemini.missed_merges) == (1, 1)
    assert bench_jev.dedup_report(result)[0]

    worse = bench_jev.evaluate_dedup(config, [cluster], probs, {ab: "same", ac: "different"})
    assert not worse.gate_ok


def test_wide_report_needs_every_merge_labelled_and_precision():
    pairs = [("p", "a", "b"), ("p", "a", "c"), ("p", "b", "c")]
    probs = {pairs[0]: (0.9, 1), pairs[1]: (0.8, 1), pairs[2]: (0.2, 1)}

    ships, unlabelled, _ = bench_jev.wide_report(pairs, probs, {}, 0.7)
    assert (ships, unlabelled) == (False, pairs[:2])
    ships, _, lines = bench_jev.wide_report(
        pairs, probs, {pairs[0]: "same", pairs[1]: "different"}, 0.7
    )
    assert not ships
    assert "labelled 2: 1 same (50.0%)" in lines[1]
    assert bench_jev.wide_report(pairs, probs, {pairs[0]: "same", pairs[1]: "same"}, 0.7)[0]


def test_wide_pairs_skips_pairs_inside_one_candidate_group(tmp_path):
    import numpy as np

    (cluster,) = bench_jev.replay_dedup(_write_dedup_night(tmp_path))
    articles = [*cluster.articles, bench_jev._dedup_article(None, "d.com", "Delta")]
    sims = np.array(
        [
            [1.0, 0.86, 0.86, 0.86],
            [0.86, 1.0, 0.95, 0.5],
            [0.86, 0.95, 1.0, 0.89],
            [0.86, 0.5, 0.89, 1.0],
        ],
    )
    pairs = bench_jev.wide_pairs("p", articles, sims, [cluster], high=0.90, low=0.85)
    assert [(a.title, b.title) for _, a, b in pairs] == [("Alpha", "Delta"), ("Gamma", "Delta")]


def test_night_merge_groups_star_groups_candidates_and_the_wider_net():
    sizes = {"A": 50, "B": 40, "C": 30, "D": 20, "E": 10}
    art = {
        h: bench_jev._dedup_article({"clean_text": "x" * n}, "s.com", h) for h, n in sizes.items()
    }
    cluster = bench_jev.DedupCluster("p", (art["A"], art["B"], art["C"]), ())
    probs = {
        bench_jev.make_pair("p", "A", "B"): (0.65, 1),  # candidate pair: >= 0.60 merges
        bench_jev.make_pair("p", "A", "C"): (0.10, 1),
        bench_jev.make_pair("p", "B", "C"): (0.90, 1),  # B is not C's keeper: no chaining
        bench_jev.make_pair("p", "A", "E"): (0.75, 1),  # wider net: >= 0.70 merges
        bench_jev.make_pair("p", "C", "D"): (0.65, 1),
    }
    wide = [("p", art["A"], art["E"]), ("p", art["C"], art["D"])]

    groups = bench_jev.night_merge_groups([cluster], wide, probs)

    assert [[a.title for a in g] for g in groups] == [["A", "B", "E"]]


def test_dedup_titles_report_lists_groups_with_a_different_member():
    night = "pipeline-2026-10-01-011209"
    labels = {bench_jev.make_pair(night, "A", "C"): "different"}
    group = [bench_jev._dedup_article(None, "s.com", h) for h in ("A", "B", "C")]
    rows = [
        bench_jev.title_row(night, group, None, {}),
        bench_jev.title_row(night, group, "A and C", labels),
    ]

    assert [m["label"] for m in rows[1]["members"]] == [None, None, "different"]
    assert bench_jev.dedup_titles_report(rows) == [
        "2 merge groups, 1 without a headline (left unmerged)",
        "[2026-10-01] A and C",
        "    different: C",
    ]
