# Bench data

Rows that a sentence in `spec/` relies on. A file stays only while a claim rests on it.
Everything else (archived pipelines, other state variants, judge runs) stays in
`~/.news_recap_data/bench/`. `scripts/bench_jev.py` produces and scores it.

## `classify-2026-10-06.jsonl`

**Claim** (`spec/plan-jev-decisions.md`, Stage 3): with the `full` state, exclude ≥ 0.75 and
vague ≥ 0.65, Jev classify passes the Stage 3.4 gate against Gemini on the three tuning nights
and on the holdout night (`pipeline-2026-10-04-011204`), at ≈ \$0.48/month.

One row per headline of the four nights with a Gemini classify verdict (1 736):

- `gemini`: agy `gemini-3.7-flash --effort low`, replayed from the archived `classify-N`
  workdirs.
- `label`, `labeler`: ground truth where labelled (348 rows, all by `claude-opus-5-5`, under
  the rules in Stage 1.2); `null` elsewhere.
- `jev_p`: `jev-1.13.0` probabilities for the `full` state (headline, source, first 300 chars
  of text). `t0`…`t4` are the exclude-policy topics in order — horoscopes, medical advice,
  sports (except Russia), Epstein files, Croatian news (unless it directly involves Serbia or
  is part of a major international event); `vague` is the vague question.
- `jev_tokens`: billed input tokens of that request.

Scoring: a row's truth is its label; an unlabelled row counts only when Jev and Gemini agree
(and then as correct — 59 of 60 sampled agreements were); every disagreement is labelled.
