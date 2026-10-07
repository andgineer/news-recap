# Bench data

Rows that a sentence in `spec/` relies on. A file stays only while a claim rests on it.
Everything else (archived pipelines, other state variants, judge runs) stays in
`~/.news_recap_data/bench/`. `scripts/bench_jev.py` produces and scores it; the conclusions
are in `spec/pipeline.md`, *Experiments → Jev decisions*. Nightly workdirs are deleted after 7
days, so `bench_jev.py snapshot` copies the nights worth keeping into the bench directory.

## `classify-2026-10-06.jsonl`

**Claim** (classify bench): with the `full` state, exclude ≥ 0.75 and
vague ≥ 0.65, Jev classify passes the gate against Gemini on the three tuning nights
and on the holdout night (`pipeline-2026-10-04-011204`), at ≈ \$0.48/month.

One row per headline of the four nights with a Gemini classify verdict (1 736):

- `gemini`: agy `gemini-3.7-flash --effort low`, replayed from the archived `classify-N`
  workdirs.
- `label`, `labeler`: ground truth where labelled (348 rows, all by `claude-opus-5-5`, under
  the classify labelling rules); `null` elsewhere.
- `jev_p`: `jev-1.13.0` probabilities for the `full` state (headline, source, first 300 chars
  of text). `t0`…`t4` are the exclude-policy topics in order — horoscopes, medical advice,
  sports (except Russia), Epstein files, Croatian news (unless it directly involves Serbia or
  is part of a major international event); `vague` is the vague question.
- `jev_tokens`: billed input tokens of that request.

Scoring: a row's truth is its label; an unlabelled row counts only when Jev and Gemini agree
(and then as correct — 59 of 60 sampled agreements were); every disagreement is labelled.

## `route-2026-10-06.jsonl`, `route-splits-2026-10-06.jsonl`

**Claim** (section routing bench): routing articles to fixed sections on Jev
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

## `dedup-2026-10-06.jsonl`

**Claims** (deduplicate bench):

- Under the one-story rule (the user's, 2026-10-07; `label`), with the production question
  (`jev_p`) merging at ≥ 0.60 inside today's candidate groups, Jev misses half as many
  same-story pairs as today's LLM dedup (53 vs 108 on the tuning nights, 0 vs 7 on the holdout)
  and makes more wrong pair merges (14 vs 8; 0 vs 0); its wider net (similarity 0.87–0.90,
  merging at ≥ 0.70) is right on 76 of 79 tuning-night merges and 8 of 9 on the holdout.
- Under the earlier rule (`label_before` where it differs, else `label`), with the earlier
  question (`jev_p_news`, `jev_merged_news`, merging at ≥ 0.40): 13 vs 31 wrong merges on the
  tuning nights, 1 vs 2 on the holdout.

One row per pair (1 875):

- `candidate`: `group` = a pair inside one of today's candidate groups (all 1 654 of the five
  nights); `wide` = a pair at similarity 0.85–0.90 outside them that either question scored
  ≥ 0.40. Production asks only `wide` pairs with `similarity` ≥ 0.87.
- `similarity`: cosine similarity of the two articles with the pipeline's embedder over the
  archived original titles and text; `null` for 22 `group` rows whose headline is not in the
  night's input.
- `gemini_merged`: today's agy `gemini-3.7-flash` put both articles in one `MERGED` group (always
  false for `wide`: today's pipeline never sees those pairs).
- `jev_p`, `jev_merged`: `jev-1.13.0` probability that the two are one story (production
  question, headline-only state) and what the pipeline merges with it — for `group`, both
  articles in one star group of their candidate group at ≥ 0.60 (keeper = longest text, so not
  recomputable from `jev_p` alone); for `wide`, `jev_p` ≥ 0.70. `null` / false where the pair
  was not asked.
- `jev_p_news`, `jev_merged_news`: the same for the earlier question (≥ 0.40 inside groups).
- `label`, `labeler`: `same` | `different` under the one-story rule, 448 pairs, all by
  `claude-opus-5-5`; `null` elsewhere. `label_before`: the earlier-rule label where it differed
  (112 pairs).

Scoring: a pair's truth is its label; an unlabelled pair counts only when Jev and the LLM agree
(and then as correct); every disagreement of the scored configurations is labelled.

## `dedup-titles-2026-10-06.jsonl`

**Claim** (merged headlines bench): when one agy launch per night writes the
headline of every Jev merge group, the headlines lose as many merged-in stories as today's LLM
dedup (1 vs 1: 8 of 9 wrongly merged members stated; today 15 of 16 groups), in the output
language, for every group.

One row per merge group of the four tuning nights (123), as `bench_jev.py dedup-titles` makes
them with the wider net at 0.85–0.90 and the earlier question (the run predates the 0.87
band and the one-story rule): the groups the pipeline
builds from the stored pair probabilities, headlines from `write_merged_titles` with agy
`gemini-3.7-flash --effort low`. An agent's output is not deterministic, so a rerun writes
different headlines and costs one launch per night.

- `written`: the headline; `null` when the launch wrote none (the group then stays unmerged;
  none here).
- `launch_tokens`, `launch_seconds`: that night's launch (the same on every row of a night).
- `members`: keeper first; `title`, `source`, `label` (the pair label against the keeper,
  `null` when unlabelled).
- `in_headline`, `read_by`: for members labelled `different`, whether the written headline states
  their story, read by `claude-opus-5-5`.
