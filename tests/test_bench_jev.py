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
    )
    (pdir / "digest.json").write_text(json.dumps({"status": status}))
    return pdir


def _bench(tmp_path: Path) -> bench_jev.Bench:
    return bench_jev.Bench(root=tmp_path / "bench", workdir_root=tmp_path / "workdir")


# --- snapshot ---------------------------------------------------------------


def test_snapshot_copies_new_and_refreshes_incomplete(tmp_path):
    bench = _bench(tmp_path)
    _write_pipeline(bench.workdir_root, "pipeline-a", ["A"])
    _write_pipeline(bench.workdir_root, "pipeline-b", ["B"], status="running")
    (bench.workdir_root / "digests.json").write_text("{}")

    assert bench_jev.snapshot(bench.workdir_root, bench.pipelines) == ["pipeline-a", "pipeline-b"]

    (bench.workdir_root / "pipeline-a" / "extra").write_text("x")
    (bench.workdir_root / "pipeline-b" / "digest.json").write_text('{"status": "completed"}')
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
    path.write_text(json.dumps({"topics": ["x", "y"], "rows": rows}))

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
    rows = [json.loads(line) for line in path.read_text().splitlines()]
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
        heads = re.findall(r"^(\d+)\. headline: (.+)$", (run_dir / "prompt.txt").read_text(), re.M)
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
