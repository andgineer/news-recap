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

## `route-2026-10-06.jsonl`, `route-splits-2026-10-06.jsonl`

**Claim** (`spec/plan-jev-decisions.md`, Stage 4): routing articles to fixed sections on Jev
before writing places follow topics as well as today's LLM, but splits 20.7% of today's
multi-article blocks across sections (21.9% on the holdout), and 11 of 259 blocks put one news
event in two sections; so routing was rejected.

`route-2026-10-06.jsonl`, one row per kept article of the five archived nights (1 758):

- `llm_follow`: the follow section today's digest placed the article in (`Russia`, `Serbia`,
  `war in Ukraine`) or `none`; `null` when the article is in no block (the writer excluded it).
- `jev_p`: `jev-1.13.0` probabilities, `url` state (headline or enriched title, source, URL,
  first 300 chars of text). `s1`…`s3` are yes-probabilities of one Noul per follow topic in the
  order above; `s4`…`s9` and `other` are one Choice over the general sections (International
  politics and security, Technology and AI, Consumer tech and guides, Economy and business,
  Science and nature, Society and culture).
- `jev_section`: the section picked with follow ≥ 0.30, confidence ≥ 0.40.
- `label`, `labeler`: accepted follow placements for the 53 follow disagreements, all by
  `claude-opus-5-5`; `boundary` tags the items labelled "either" (Kosovo, Republika Srpska).

`route-splits-2026-10-06.jsonl`, one row per block of today's digests that the picked sections
split (54): the block's headlines, `same_story` (the split separates reports of one news event),
`story`, and `follow_angle` where a follow section got a local reaction to the event.
