# Plan: Jev Decides the Structure, the LLM Writes

Status: proposed (2026-10-05). Related: `plan-token-optimization.md` (its Phases 5–6, local
clustering and the local classify cascade, are superseded by Stages 3–5 here), issue #18
(Stage 0).

## Goal

Two outcomes, each measured against a baseline recorded under *Evidence*:

1. **A digest every night.** Baseline: 21 of 32 nights (2026-09-04 … 10-05).
2. **A better digest, as judged by its reader:** fewer duplicate entries inside blocks, follow
   topics always in their own section, the same sections every day, no more wrongly dropped
   stories than today, and block quality no worse.

Means: every *decision* (exclude / vague, which section, same news?) moves to TypeSafe's Jev;
the LLM (agy) only *writes* (enriched headlines, block descriptions, section summaries). The
pipeline is reshaped around Jev's cost model instead of swapping LLM calls one for one:

- An LLM launch is expensive and unreliable per item, so today's pipeline packs hundreds of items
  into a few prompts and then repairs the side effects: recognition-rate guards, BlockDedup,
  MergeSections (sections invented independently per batch), RefineLayout (orphan sections), and
  an embedding pre-filter that keeps dedup launches few.
- A Jev request costs ~\$0.00003, answers every item (no dropped or miscounted lines) and
  returns probabilities, but cannot write. So Jev makes many small independent decisions up
  front, the LLM writes inside a structure that is already fixed, and the repair steps lose
  their reason to exist.

## Evidence (measured 2026-10-05)

### Nightly runs, 2026-09-04 … 2026-10-05

| Cause | Nights |
|---|---|
| agy quota — 4 lockouts: daily 09-10; weekly 09-16, 09-22/23, 10-01/02 | 6 |
| `load_resources` failure-rate gate (09-07, 09-27, 10-04) — issue #18 | 3 |
| `claude: agent exit code 1` (09-24, 09-25, not investigated) | 2 |

Every log ends with `RESULT: OK`: `recap_flow` catches `RecapPipelineError`, so `create`
exits 0 on a failed pipeline.

agy launches per completed night (21 nights, median): classify 3, enrich 1, dedup 4,
oneshot_digest 2, merge_sections 1, refine_layout 1 — total 12.

### What agy's quota counts

agy reports "Individual quota reached", not a request count, and the launch count alone does not
predict lockouts: 09-10 hit the daily cap at its 11th launch, while 09-18 and 09-26 ran 17
launches each without hitting it. The two fully observed weekly windows locked out after 56 and
64 launches. Every agy launch writes `tokens_used: null`; each launch is a multi-turn agent
session plus a separate title-generation model call (visible in `agent_stderr.log`).

On the 4 archived nights the four decision steps (classify, dedup, merge_sections,
refine_layout) are 76% of launches, 46% of prompt bytes and 36% of output bytes. Removing them
leaves ~24 launch-equivalents a week if the quota follows launches, or ~45 if it follows tokens:
under the observed lockouts either way, but with only ~20% headroom in the second case.
Stage 0.5 measures which.

### Jev

`jev-1.13.0`: \$0.042 per million **input** tokens (output free); 100K tokens/s and 80 req/s
(limits "adjusting dynamically"); 64k tokens per request, 32k for state + longest question;
English is the primary language, others "handled but not equally well". Jev never generates
text: it answers Noul (yes/no probability), Choice (one of N, with per-option probabilities)
and Score questions about a `state`.

### Jev vs Gemini on classify

Data: 1 765 headlines from the 4 archived nights; per-headline probabilities in
`~/.news_recap_data/bench/jev-exp-2026-10-05/generic2_1765.json`. Design: the exclude policy
split on top-level commas, one Noul per topic plus a vague Noul; state = headline, source, first
300 chars of text; exclude ≥ 0.6, vague ≥ 0.7. Cost 1.38M tokens (≈783 tokens/headline), ~30 s
at 16 concurrent requests. Gemini = agy `gemini-3.7-flash --effort low`.

Rows = Gemini, columns = Jev:

| | ok | vague | exclude |
|---|---|---|---|
| ok | 1 286 | 43 | 37 |
| vague | 43 | 24 | 31 |
| exclude | 6 | 2 | 293 |

- Overall agreement 90.8%; exclude-vs-keep agreement 95.7%.
- **Vague barely agrees:** Jev calls 24 of Gemini's 98 vague headlines vague; 119 of the 162
  disagreements involve vague.
- **Language bias remains:** sampled Jev-only excludes are mostly Croatian-language stories not
  about Croatia (a shark in South Korea, the Pope on AI, a fast-food/depression study), despite
  the instruction to judge by subject, not by the outlet's language.
- Confidence bands (max exclude probability): < 0.2 covers 55% of headlines at 99.9% exclude
  agreement; ≥ 0.85 covers 10% at 94.5%; the middle 34% agrees 89.3%.
- Gemini is a reference, not ground truth; its own error rate is unknown. Stage 1 supplies
  ground truth.

### Today's digests (4 archived nights)

- 239–386 kept articles → 34–65 blocks (median 2–3 articles per block, max 24) → 7–9 sections;
  0–3 sections with ≤ 2 blocks; all section titles Russian.
- The same core sections recur every night (Война в Украине, Россия, Сербия, Технологии…,
  Международная политика…) with wording drift: section-title Jaccard between consecutive
  nights is 0.23–0.27.
- Dedup (embedding ≥ 0.90 pre-filter + LLM) removes 9–41 articles a night but misses paraphrases
  and translations: the 09-29 block on Vučić's resignation lists 12 articles, at least five of
  them separate reports of the same handover, including two Serbian reports from the same day
  ("Ana Brnabić v.d. predsednika…", "Ana Brnabić vršiteljka dužnosti…").
- Within-block article pairs per night: 126–989.

## Target pipeline

```
classify (Jev) → load_resources → enrich (LLM) → route (Jev) → oneshot_digest (LLM) → collapse_duplicates (Jev)
```

- **classify** — Jev: exclude via one Noul per policy topic, vague via one Noul.
- **route** — Jev Choice per article over a fixed section list: follow topics + general
  sections + "other".
- **oneshot_digest** — the LLM receives articles already grouped by section, groups each
  section's articles into blocks, and writes block descriptions and section summaries. A section
  is never split across launches unless it alone exceeds the batch size, so no step has to
  reconcile sections invented per batch.
- **collapse_duplicates** — Jev "same piece of news?" for every article pair inside each block;
  duplicates fold into the keeper's `alt_urls`. The LLM's grouping supplies the candidates, so
  translations and paraphrases are caught.
- **Deleted:** the `deduplicate` step (embedding pre-filter + LLM), `merge_sections`,
  `refine_layout`.
- **Kept:** BlockDedup phases 1–3. Phase 3 (fuzzy title merge) also repairs a story that routing
  split across two sections.

agy launches per night: enrich 1 + oneshot_digest 2 = 3, plus one when the section list or the
output language changes (title translation, cached).

## Decisions

1. **Use `typesafe-sdk` directly**, not the `jev` wrapper: `jev` requires Python ≥ 3.14 and
   discards the probabilities the thresholds need.
2. **Key lookup**, first hit wins: env `TYPESAFE_API_KEY` → `./.env` → `<data_dir>/.env`.
   Read with `dotenv_values()`, never written to `os.environ`. `TYPESAFE_API_KEY` is always
   stripped from agent subprocess env (agents read untrusted news text with permissions
   skipped).
3. **Pinned model** `jev-1.13.0`; thresholds are tuned against it. Upgrading = rerun the bench,
   then bump.
4. **Thresholds are module constants**, set from the bench.
5. **Jev failure:** SDK retries, then `JevUnavailable`.
   - In classify: warning, the step reruns on the LLM path (kept until Stage 7).
   - In route and collapse_duplicates: `RecapPipelineError`. The night fails visibly (exit 1
     after Stage 0.3) and resumes from the checkpoint on the next run. No LLM twin is kept for
     these steps; the classify fallback count during Stages 3–6 is the measured Jev
     availability behind this choice.
6. **Section list** = follow topics (from `preferences.follow`) + general sections (new
   user-config key `sections`, same comma syntax as `exclude`/`follow`, default seeded in
   Stage 4) + "other".
   - Routing uses English names and descriptions (Jev's strongest language).
   - Display titles in the output language come from a one-time LLM translation cached per
     (section list, language, prompt) hash, so titles are identical every night.
7. **Gates require improvement** wherever the reader can see the difference; non-inferiority
   only where a gate says so. Ground truth is the user's labels; the Sonnet judge is used only
   for tasks where its agreement with the user's labels has been measured.
8. **A wrongly excluded story is worse than a wrongly kept one** (the reader never sees it), so
   wrong excludes are gated separately.
9. **Bench data** lives in `~/.news_recap_data/bench/`. Only the rows a spec sentence relies on
   are committed (`bench/` in the repo, with a README naming the claim each file supports).

## Stage 0 — Reliability and telemetry (~0.5 day, independent of Jev)

0.1 **`load_resources` stops failing the pipeline** (issue #18). **Done 2026-10-05** (319440b,
#18 closed).
`recap/tasks/load_resources.py`: replace the `raise RecapPipelineError(...)` at the
`_MAX_FAILURE_RATE` check (line 117) with `logger.warning(...)` naming the rate; keep the
constant as the warning threshold. Failed articles are already reset to `verdict = "ok"` above
it. Tests (`tests/test_load_resources.py`): `test_high_failure_rate_raises` becomes
`test_high_failure_rate_warns` (no raise, warning logged, `enrich_ids` contains only loaded
ids); `test_high_failure_persists_loaded_before_raise` becomes a check that loaded ids are
persisted and the step completes.

0.2 **Honest User-Agent**, gated by a probe. **Done 2026-10-05:** the honest UA loses tanjug.rs
(nginx 403 for any non-browser UA), so the default is `... Chrome/129.0 Safari/537.36`, the only
probed UA that passes engadget, tanjug.rs and slashdot (Chrome/141 and Firefox/143 get 403 from
slashdot). Probe table in 319440b.
`http/fetcher.py:14` `DEFAULT_USER_AGENT` currently is `... Chrome/131.0.0.0 Safari/537.36`,
which engadget.com's CloudFront answers with 403 (60 of the 80 failed downloads); the same
URL returns 200 for `news-recap/1.9 (+https://github.com/andgineer/news-recap)` and for
`... Chrome/129.0 Safari/537.36`. Before switching, run `scripts/probe_sources.py` over the
domains from the archived `pipeline_input.json` files with both UAs.

- If the honest UA loses no domain, use
  `f"news-recap/{__version__} (+https://github.com/andgineer/news-recap)"`.
- Otherwise use the best-scoring browser UA from the probe.

Either way, record the probe table in the commit message.

0.3 **`create` exits 1 when the pipeline failed.** **Done 2026-10-05.**
`recap/launcher.py` `_emit_run_summary` (line 143) returns silently for non-completed digests,
so no `Workdir:` line is emitted. Change it to yield
`("error", "Pipeline failed — no digest produced")` and the `Workdir:` line for any status
other than `completed`. Add `RecapRunFailedError(click.ClickException)` (exit code 1) and raise
it at the end of `RecapCliController.run_pipeline` when the digest status is `failed`. In
`main.py` `_emit_pipeline`, print the stage table in a `finally:` so the table still appears.
All three schedule templates (`src/news_recap/scripts/macos_run.sh`, `linux_run.sh`, `windows_run.ps1`)
already turn a non-zero exit into `RESULT: FAILED`. Test: `CliRunner` invoking `create`
with a flow that fails returns `exit_code == 1`, and the output contains "Pipeline failed".

0.4 **Archive: done 2026-10-05.** The four workdirs are in
`~/.news_recap_data/bench/pipelines/`, the Jev experiment (scripts, dataset, probabilities) in
`~/.news_recap_data/bench/jev-exp-2026-10-05/`. Workdirs are deleted after 7 days
(`gc_retention_days`), so until Stage 6 ends run `bench_jev.py snapshot` (Stage 1) at least
every 5 days.

0.5 **agy consumption telemetry.** One probe launch: `agy --output-format json -p "Reply OK"`
(`-p` must come last). **Done 2026-10-05:** the envelope carries input, output, thinking,
cache-read and total tokens; the first branch below is implemented and documented in
`spec/agents.md`. "Reply OK" costs 12,921 input tokens (per-launch agent overhead); a
20-headline classify launch costs 25,117 input + 2,245 output.

- If the JSON carries token usage: for antigravity, add `--output-format json` to the command
  template, parse the envelope in `recap/agents/ai_agent.py`, write the result text back as the
  stdout the parsers expect, and save the tokens in `meta/usage.json`. The claude envelope
  design in `plan-token-optimization.md` Phase 1 item 3 applies unchanged (usage parsed before
  the empty-stdout check; `_summarise_output` scans the extracted text).
- If not: record that in `spec/agents.md`. Consumption is then measured as launches plus
  `prompt_bytes`/`output_bytes`, which `digests.json` already records per run.

## Stage 1 — Ground truth (~0.5 day + ~30 min of labelling)

1.1 New `scripts/bench_jev.py`; subcommands are added per stage:
`snapshot | label | judge-check | classify | route | ab | report` (+ `dedup` in Fallback B).
It reads `TYPESAFE_API_KEY` the same way as the pipeline (Decision 2). This stage implements:

**Done 2026-10-05** (`scripts/bench_jev.py`, `tests/test_bench_jev.py`). Differences from the
bullets below:

- `snapshot` also re-copies an archived pipeline whose `digest.json` is not `completed`, so a
  night that resumes after a failure does not stay archived half-done. Copies go through a temp
  dir and a rename.
- `label`: `s` records `skip`; skipped items are not shown again and count as unlabelled for
  every gate. `q` (or Ctrl-C) quits. `u` undoes labels from the current session only. Without
  `--items` it presents the 1.2 batch; `--items` takes a JSONL file of `{pipeline, headline}`.
- `judge-check --task classify`: `claude -p --model claude-sonnet-5-5 --tools ""
  --no-session-persistence`, prompt on stdin from `prompt.txt` (no tools, so injected text in
  the news cannot act), with `ANTHROPIC_API_KEY` (would bill the API, not the subscription) and
  `TYPESAFE_API_KEY` stripped. Answers are cached in `bench/judge/classify.jsonl` keyed by
  model + prompt hash, so a rerun only judges new labels. Run logs are kept in
  `bench/judge/runs/`.
- Reading `TYPESAFE_API_KEY` waits for `classify` (Stage 3): no Stage 1 subcommand calls Jev,
  and Stage 2's `make_jev_client` will provide the lookup.

- `snapshot`: copy `<data_dir>/workdir/pipeline-*` into `<data_dir>/bench/pipelines/`,
  skipping existing ones.
- `label`: present items blind and in random order — headline, source, first 300 chars of
  text, and the exclude policy; keys `o` ok, `v` vague, `x` exclude, `s` skip, `u` undo.
  Appends `{pipeline, headline, label, labeled_at}` to `bench/labels/classify.jsonl`;
  resumable. It takes a list of items, so later stages can request labels on demand.
- `judge-check`: run the judge (see *Bench*) on labelled items of one task and print its
  agreement with the user.

1.2 First labelling batch, ~220 items (~30 min): all 162 disagreements of the experiment
design above, plus 60 random agreements (fixed seed). Jev and Gemini differ only on
disagreements, so labelling all of them gives an exact comparison; the 60 agreements estimate
how often both are wrong together.
**Done 2026-10-05, labelled by Claude (Opus 5.5) at the user's request**, not by the user:
rows carry `labeler: claude-opus-5-5`. 222 items (seed 20261005): 184 from the tuning nights,
38 from the holdout. Labels: ok 142, vague 54, exclude 26. Rules (the user confirmed the
medical, sports and vague boundaries on 2026-10-05; later labels follow them): exclude = the
story's subject (not the outlet's language) is Croatian domestic affairs, non-Russian sports,
health/wellness advice to the reader (symptoms, diet, sleep, anxiety tips), horoscopes or the
Epstein files; health *research news* and local notices caused by a sports event are not
excluded. vague = the headline withholds the fact it is about (an unnamed entity: "a famous
singer", "this setting", "two countries", "33 things"; a teaser question; a puzzle or show
title); guide questions ("Is X worth buying?") and deal posts are ok.

Results against these labels (experiment design, exclude ≥ 0.6, vague ≥ 0.7):

- 162 disagreements: Gemini right on 83, Jev on 70, neither on 9. Of the 60 agreements,
  59 are right.
- Wrong excludes: Gemini 7, Jev 50 (44 Croatian-language stories not about Croatia, 6
  sports-adjacent). Missed excludes: Gemini 18 (14 of them Croatian domestic stories Gemini
  called vague), Jev 1.
- Jev exclude threshold, on the 222 labelled items only: 0.7 → 8 wrong / 3 missed; 0.8 → 3 / 8;
  0.85 → 0 / 14. Other thresholds create disagreements outside the labelled set (e.g. 9 of
  the 293 joint excludes have Jev max p < 0.7), so Stage 3 labels those before the gate.
- `judge-check` (Sonnet): 74.3% agreement, **not calibrated** for classify. 36 of the 57
  disagreements are labelled vague, judge ok (the judge reads vague narrowly); 12 are on the
  exclude boundary (Croatian stories whose country appears only in the text, wellness
  advice). Classify gates use labels directly, so Stage 3 does not depend on the judge.

1.3 Night 2026-10-04 (277 headlines) is the holdout: thresholds and state variants are tuned
on the other three nights only (`HOLDOUT_PIPELINE` in `bench_jev.py`).

## Stage 2 — Jev foundation (~1 day, no behaviour change)

2.1 `pyproject.toml`: add `typesafe-sdk>=0.7.2`, `python-dotenv>=1.0`. Run `uv lock`.

2.2 `config.py`: new `JevSettings` dataclass on `Settings`: `api_key: str | None`,
`model: str = "jev-1.13.0"`, `max_concurrency: int = 16`, `price_per_mtok: float = 0.042`,
`classify_backend: str`.

- `from_env` resolves the key per Decision 2.
- `NEWS_RECAP_CLASSIFY_BACKEND=llm|jev`; other values raise `ValueError`. Default `llm` in
  this stage. Without a key, `jev` is forced to `llm` with one warning.

2.3 `PipelineInput` (`recap/storage/pipeline_io.py`): add `jev_model: str` and
`classify_backend: str` (no key — `pipeline_input.json` sits in the workdir). The launcher fills
them from `Settings`.

2.4 `recap/agents/ai_agent.py:407–413`: pop `TYPESAFE_API_KEY` from `env` unconditionally,
next to the existing `api_key_vars` stripping.

2.5 New package `src/news_recap/recap/jev/`:

- `client.py`
  - `class JevUnavailable(RecapPipelineError)`
  - `class JevClient` wrapping `AsyncTypeSafeClient`, with
    `decide(requests: list[tuple[JSONContent, dict[str, Question]]]) -> list[SystemOneResponse]`.
    It runs `asyncio.run` with a semaphore of `max_concurrency` and accumulates `input_tokens`
    and request count. It maps `TypeSafeError` and its subclasses (auth, rate-limit after SDK
    retries, timeout, connection) to `JevUnavailable`.
  - `make_jev_client(data_dir: Path, model: str) -> JevClient | None`: key lookup per
    Decision 2.
- `usage.py`
  - `save_jev_usage(task_dir, *, elapsed, input_tokens, requests, model, price_per_mtok)`
    writes `meta/usage.json` with `backend: "jev"`, `tokens_used` = `total_tokens` = input
    tokens, `requests`, `model`, `cost_usd`. Field names stay compatible with
    `read_agent_usage` and the aggregator at `recap/pipeline_setup.py:187–194`.
  - `save_answers(task_dir, rows)` writes `output/jev_answers.json`: per-item probabilities.
  - Jev task dirs are named `<step>-jev` (e.g. `classify-jev`) so the stage table lists them.
- `policy.py`
  - `split_policy_topics(text: str) -> list[str]`: split on commas at parenthesis depth 0,
    strip, drop empties (doctests). Used by classify, route and the `sections` key.

Tests:

- key lookup precedence (env > cwd `.env` > data-dir `.env`);
- the key never appears in `os.environ`;
- `TYPESAFE_API_KEY` is absent from the agent env even when set in the process env;
- backend parsing and validation, including the no-key downgrade;
- `JevClient` error mapping with a fake async client;
- `save_jev_usage` round-trips through `read_agent_usage`.

## Stage 3 — Classify on Jev (~1 day + bench)

3.1 `recap/jev/classify.py`:

- `topic_question(topic) -> Noul`, instruction text from the experiment:
  > Is the subject of this news story covered by the excluded topic "{topic}"? Judge by what the
  > story is about (its events, people, places), not by the country or language of the outlet
  > that published it. Apply any exception stated in parentheses: a story covered by the
  > exception is not excluded.
- `VAGUE_QUESTION`: the experiment's vague Noul (teaser, rhetorical question or deliberate
  omission that hides what happened).
- `article_state(a, variant)`; variants the bench compares: `full` (headline, source,
  `clean_text[:300]`), `no_source`, `headline_only`.
- `verdict(probs) -> str` with `EXCLUDE_THRESHOLD`, `VAGUE_THRESHOLD`.
- `classify_articles(client, articles, policy) -> dict[str, tuple[str, dict[str, float]]]`.

3.2 `Classify.execute` (`recap/tasks/classify.py:234`): when `classify_backend == "jev"`, set
`a.verdict` on each `to_classify` article from `classify_articles`, then call the existing
`_sync_verdicts` (state, `kept_entries`, `enrich_ids` and the log line unchanged). On
`JevUnavailable`, log a warning and run the existing batch flow. The 80% recognition guard does
not apply to the Jev path (every article gets an answer or the call raises).

3.3 `bench_jev.py classify`:

- replay the three tuning nights from the archive: parse each
  `classify-N/input/task_prompt.txt` (section after `=== HEADLINES`, lines `N: headline`) and
  its `output/agent_stdout.log` (`N: ok|vague|exclude`); join to `pipeline_input.json` articles
  by title for `source` and `clean_text`;
- run each state variant once and store probabilities in
  `bench/runs/classify-<variant>-<date>.jsonl`;
- sweep `EXCLUDE_THRESHOLD` ∈ {0.4…0.8} × `VAGUE_THRESHOLD` ∈ {0.5…0.9} from stored
  probabilities (no new calls);
- collect the unlabelled disagreements of the best few configurations and pass them to `label`
  (expected: tens of items);
- report per class against labels, for Jev and Gemini: correct count, precision, recall, and
  wrongly excluded count;
- run the chosen configuration on the holdout night, label its disagreements, print the same
  report.

3.4 Gate, checked on the holdout night and on the tuning nights separately:

- **exclude**: Jev's wrong excludes ≤ Gemini's, and Jev's correct exclude/keep decisions
  ≥ Gemini's;
- **vague**: Jev's F1 against labels ≥ Gemini's − 0.05 (non-inferiority: a vague error costs one
  unneeded rewrite or leaves one teaser headline);
- projected Jev cost for classify < \$1/month.

Outcomes:

- Pass → default `classify_backend=jev` when a key is present; update the threshold constants;
  commit the bench rows the spec cites.
- Fail on vague only → Jev decides exclude; the existing LLM classify prompt runs on the
  Jev-kept headlines for vague only (its `exclude` answers are treated as `ok`), so classify
  launches stay until more labels settle vague.
- Fail on exclude → classify stays on the LLM. Stages 4–6 still apply (they do not depend on
  classify).

## Stage 4 — Routing go/no-go (offline, ~0.5 day, ≈ \$0.05 of Jev)

4.1 Seed the general sections from the section titles of the 4 archived digests (English name
+ description):

- International politics and security (diplomacy, conflicts, elections and governments outside
  the follow topics, including US politics)
- Technology and AI (AI, software, internet companies, cybersecurity, tech regulation)
- Consumer tech and guides (gadgets, reviews, deals, how-tos)
- Economy and business
- Science, climate and nature
- Society and culture (education, media, film, games, the arts)

Follow topics (today: Russia, Serbia, war in Ukraine) come from preferences; "other" is
appended.

4.2 `recap/jev/route.py`:

- `section_question(sections) -> Choice`: criteria
  `{"s1": "<name>: <description>", …, "other": "No listed section clearly fits."}`; instructions
  "Which section of a daily news digest does this story belong to? Judge by what the story is
  about, not by the language or country of the outlet."
- `pick_section(probabilities) -> str`: if any follow section has p ≥ `FOLLOW_THRESHOLD`
  (initial 0.35), take the most probable follow section; else the argmax; if that p
  < `MIN_ROUTE_CONFIDENCE` (initial 0.4), "other". The follow precedence keeps a Serbia story
  out of "International politics" when both fit.
- state = `article_state(a, "full")`, using `enriched_title` when present.

4.3 `bench_jev.py route` over the kept articles of the 4 archived `digest.json` files,
sweeping both thresholds from stored probabilities:

- **split rate**: share of today's multi-article blocks whose articles land in > 1 section;
- **other share**: share of articles routed to "other";
- **follow agreement**: of the articles the LLM put in a follow section, the share routed to
  that section, and the reverse; disagreements go to the judge, and 20 of them to the user as a
  spot-check;
- section sizes per night.

4.4 Gate: split rate ≤ 10%, other share ≤ 15%, and on judged follow disagreements Jev right
≥ LLM right.

- Split rate too high → route by majority vote within embedding clusters (`reorder_articles`
  groups at 0.65) and re-measure.
- Still failing → Fallback B (Appendix); Stages 5–6 are skipped.

## Stage 5 — Build the restructure (~3 days, on a branch)

5.1 Preferences: `UserPreferences.sections: str` (default from 4.1); add `sections` to
`user_config.py` `_KNOWN_KEYS` and to the prompts in `operation_configure.py`. `PipelineInput`
carries it inside `preferences`.

5.2 Section titles: `recap/section_titles.py`.

- `section_titles(ctx, sections) -> dict[str, str]` reads
  `<data_dir>/sections/titles-<hash>.json`; the hash covers the section list, the output
  language and the prompt body.
- On a miss: one LLM launch (`recap_section_titles`, new entry in the `config.py` task maps)
  with the numbered English names, output `N: <title>` in the output language; parse, check the
  count, save. "other" is translated in the same call.

5.3 `Route` step (`recap/tasks/route.py`, `name = "route"`):

- `DigestArticle.section: str | None = None` (the default keeps old checkpoints loadable);
- `execute` routes every article in `ctx.digest.articles` without a section, then writes
  `route-jev/` usage and answers;
- `restore_state` is a no-op (the section is persisted in the digest).

5.4 `OneshotDigest` (`recap/tasks/oneshot_digest.py`):

- group `ctx.digest.articles` by `section`; order each group with `reorder_articles` (existing
  embedder and `oneshot_digest_order.json`);
- pack sections into launches of ≤ `_BATCH_SIZE` articles, first-fit decreasing; a section
  larger than `_BATCH_SIZE` is cut into chunks, with a log line;
- new `RECAP_ONESHOT_DIGEST_PROMPT` body:
  - articles listed under `=== SECTION <id>: <English name> ===` headers, numbered globally;
  - the model outputs `SECTION: <id>`, `SECTION_SUMMARY:`, `BLOCK:`/`ARTICLES:` and
    `EXCLUDED:`;
  - it never creates or renames sections and never moves an article to another section;
  - the "EDITORIAL FOCUS — KEEP SEPARATE" paragraph and the section-label instruction (task
    item 4) are removed; the block-writing instructions (task item 3, no catch-all block,
    every number exactly once) stay;
- parser: `SECTION: <id>` maps to the section; a block under an unknown id, or one whose
  articles come from several sections, goes to the section holding most of its articles
  (counted and logged as `cross_section_blocks`);
- `_build_digest_entries` builds sections in a fixed order (follow topics, general sections in
  list order, "other" last) with titles from 5.2 and summaries from the model; empty sections
  are dropped; chunks of one oversized section are concatenated;
- delete `_run_merge`, `_parse_merge_output`, `_MergedSection`,
  `_build_merged_digest_entries` and `RECAP_MERGE_SECTIONS_PROMPT`;
- keep `_dedup_blocks` and `_fuzzy_merge_blocks`;
- batch cache: keep `batch_num_to_id.json`, add `batch_sections.json`; a cached batch is reused
  only if its section composition matches.

5.5 `CollapseDuplicates` step (`recap/tasks/collapse_duplicates.py`,
`name = "collapse_duplicates"`) with `recap/jev/collapse.py`:

- `PAIR_QUESTION` Noul: "Do article_a and article_b report the same specific news event, so a
  reader would consider them the same piece of news (not merely related stories)?"; state
  `{headline_a, headline_b}` (enriched title when present). The bench tests adding leads.
- For each block with ≥ 2 articles, ask all pairs.
- Star grouping, no chaining: articles sorted by `len(clean_text)` descending; each joins the
  first existing group whose keeper it matches at ≥ `SAME_EVENT_THRESHOLD` (initial 0.5, the
  experiment's best), otherwise it starts a new group.
- Non-keepers go to the keeper's `alt_urls` and are removed from `block.article_ids` and
  `ctx.digest.articles`; the keeper's title is unchanged (the block description already
  carries the story).
- `restore_state` is a no-op.

5.6 Delete:

- `recap/tasks/refine_layout.py`, `RECAP_REFINE_LAYOUT_PROMPT`,
  `tests/recap/tasks/test_refine_layout.py`;
- `recap/tasks/deduplicate.py`, the dedup prompts in `prompts.py`, `tests/test_deduplicate.py`,
  `tests/recap/tasks/test_deduplicate.py`, and the parts of `tests/recap/tasks/test_dedup_helpers.py` that
  cover only deleted code; `recap/dedup/cluster.py` stays (fuzzy merge, ordering);
- `config.py` task-map entries `recap_dedup`, `recap_merge_sections`, `recap_refine_layout`;
- `PipelineInput.dedup_threshold` (old `pipeline_input.json` files still load: fields are read
  with `raw.get`).

5.7 Phase graph:

- `flow.py`: `Classify, LoadResources, Enrich, Route, OneshotDigest, CollapseDuplicates`;
- `main.py:240` `--stop-after` choices: `classify, load_resources, enrich, route,
  oneshot_digest, collapse_duplicates`; the same list in `docs/src/en/cli.md` and
  `docs/src/ru/cli.md`;
- old checkpoints resume: `deduplicate` or `refine_layout` in `completed_phases` is ignored.

5.8 Tests:

- `tests/recap/tasks/test_route.py`: follow precedence, low confidence → "other", a persisted section is not
  re-routed, `JevUnavailable` → `RecapPipelineError`;
- `tests/recap/tasks/test_oneshot_digest.py`: packing never splits a section smaller than `_BATCH_SIZE`, the prompt
  carries section headers, id mapping, unknown id → majority section, fixed section order,
  cached batch reused only on matching composition;
- `tests/recap/tasks/test_collapse_duplicates.py`: star grouping (A≈B, B≈C, A≉C → C does not join A's group),
  keeper choice, `alt_urls`, removal from blocks and articles;
- `tests/recap/test_section_titles.py`: cache hit; miss → one launch; the hash changes with list, language
  and prompt;
- `tests/recap/test_flow.py`, `tests/recap/test_pipeline_setup.py`: new phase list; a checkpoint with old phase names
  resumes.

## Stage 6 — Side-by-side week (7 nights)

6.1 `bench_jev.py ab` replaces the plain `create` in the scheduled job for the week:

1. production (main): `news-recap create --stop-after enrich`;
2. copy the pipeline dir to `<data_dir>/bench/ab/<date>/b/`;
3. resume production to completion — arm A, today's pipeline after Stage 3;
4. in a worktree of the branch, `recap_flow(<copy>, <date>)` — arm B.

Both arms start from identical classify, load_resources and enrich output, so only the structure
differs. agy cost: arm A ≈ 9 launches + arm B 2 = 11 a night, about today's load, so a lockout
is possible near the end of the week; a locked night is skipped, not repeated.

6.2 Reader verdict: `bench_jev.py ab --review <date>` renders both digests with
`web/templates/digest.html` as "A"/"B" in random order and records
`{date, preferred: A|B|same, notes}` to `bench/ab/verdicts.jsonl`.

6.3 Metrics per arm per night (`bench_jev.py report`):

- agy launches, `prompt_bytes`, `output_bytes`, agy tokens if Stage 0.5 found them; Jev tokens
  and \$;
- sections, blocks, sections ≤ 2 blocks, coverage, writer-excluded articles,
  `cross_section_blocks`, fuzzy merges;
- section-title Jaccard vs the previous night of the same arm;
- **duplicates left in blocks**: the judge on 100 random within-block pairs per arm per night;
- **collapse precision** (arm B): the judge on 50 collapsed pairs;
- **block coherence**: the judge on 30 random multi-article blocks per arm ("do all articles
  describe one story?");
- **follow leaks**: the judge on articles about a follow topic placed outside its section,
  sampled from both arms.

6.4 Gate:

- the reader prefers B on ≥ 5 of 7 nights (≥ 4 of 5 if lockouts cut the week);
- fewer duplicates left in blocks in B; collapse precision ≥ 90%;
- block coherence in B not lower than in A by more than 5 points (non-inferiority);
- follow leaks in B ≤ A.

Pass → merge the branch. Fail → do not merge; Fallback B (Appendix).

## Stage 7 — Docs and cleanup (~0.5 day)

- `spec/pipeline.md`:
  - overview and per-step contracts for classify (Jev), route, oneshot_digest and
    collapse_duplicates; Deduplicate, MergeSections and RefineLayout removed;
  - the Cost section rewritten (agy launches per night, Jev \$/month);
  - bench conclusions under Experiments, citing the committed `bench/` rows.
- `README.md`, `docs/src/en/`, `docs/src/ru/`:
  - `TYPESAFE_API_KEY` and the two `.env` locations;
  - the `sections` setting;
  - write exclude topics as subjects ("Croatian domestic news", not "Croatian news"), since Jev
    reads topics literally;
  - the new `--stop-after` values.
- `spec/plan-token-optimization.md`: mark Phases 5–6 superseded by this plan.
- `bench/README.md`: each committed run file and the spec sentence relying on it. A run stays
  only while a claim rests on it.
- LLM classify fallback: if it never triggered over ≥ 14 nights, delete the LLM classify path,
  its prompt and `classify_backend`; otherwise keep it and record the observed failure rate in
  `spec/pipeline.md`.

## Bench

- **Judge**: Claude Sonnet via the `claude` CLI (subscription, not the agy quota), prompts
  passed as files like the existing `experiment_*.py` scripts. Items are packed 20 per call;
  the output is `N: <answer>`. Comparisons show both answers as A/B in random order.
- **Judge calibration**: a judge task is used only after `judge-check` shows ≥ 90% agreement
  with the user on ≥ 30 labelled items of that task. Classify uses the Stage 1 labels; for
  duplicates, block coherence and follow placement the user labels 30 items each the first
  time the task is needed.
- **Spot-check**: every report prints 20 random judged items.
- **Cost report**: Jev input tokens × \$0.042/M per step; per night (median and max) and
  projected per month; agy launches and bytes per night before and after.
- **Budget**: < \$1 of Jev for all bench runs; a few hundred judge calls on the Claude
  subscription.

## Verification

```bash
uv run pytest --cov=src tests/
inv pre
uv run python scripts/bench_jev.py snapshot
uv run python scripts/bench_jev.py label          # Stage 1
uv run python scripts/bench_jev.py classify       # Stage 3
uv run python scripts/bench_jev.py route          # Stage 4
uv run python scripts/bench_jev.py ab             # Stage 6, nightly
uv run python scripts/bench_jev.py report
NEWS_RECAP_CLASSIFY_BACKEND=jev news-recap create --stop-after classify
```

The last command must show a `classify-jev` row with tokens and cost in the stage table and
create no `classify-N` workdirs. After Stage 5, a full `news-recap create` shows `route-jev`,
`oneshot_digest-N` and `collapse_duplicates-jev` rows and no `dedup-N`, `merge_sections` or
`refine_layout` workdirs.

Manual, once: put `TYPESAFE_API_KEY` into `~/.news_recap_data/.env` so the scheduled job
(launchd starts it with cwd `/`) finds it.

## Expected impact

| After | agy launches/night (median) | Jev \$/month | Measured quality change |
|---|---|---|---|
| Stage 0 | 12 | 0 | nights lost to `load_resources`: 3/32 → 0 |
| Stage 3 | 9 | ≈ 0.45 | wrong excludes vs labels ≤ Gemini's |
| Stage 6 pass | 3 (+1 when the section list changes) | ≈ 1.05 | reader preference, fewer duplicates, follow leaks ≤ today |
| Fallback B | 5 | ≈ 0.5 | none beyond Stage 3 |

Jev per night after Stage 6: classify ≈ 0.35M tokens, route ≈ 0.25M (~360 articles × ~700
tokens), collapse ≤ 0.25M (≤ 1 000 pairs) — ≈ \$0.035 a night.

## Risks

- **Routing splits a story** across sections (an English report in "International politics",
  the Serbian ones in "Serbia"): measured in Stage 4, partly repaired by fuzzy merge, gated in
  Stage 6.
- **Fixed sections lose day-specific ones** (a one-off crisis section): such stories land in the
  closest general section or "other"; the other-share gate bounds it, and the user extends
  `sections` when a topic recurs.
- **A Jev outage** fails route/collapse for that night (Decision 5); the classify fallback count
  measures how often that would happen.
- **Rate limits** are "adjusting dynamically": SDK retries; the experiment used 16 concurrent
  requests against the documented 80 req/s.
- **Free-text policies and section descriptions are read literally**: docs tell users to phrase
  topics as subjects.
- **The `jev-latest` alias moves**: the model is pinned (Decision 3).

## Appendix — Fallback B: dedup on Jev, merge/refine on the LLM

Used if Stage 4 or Stage 6 fails. agy launches 12 → 5 (enrich 1, oneshot 2, merge 1, refine 1).

- `recap/jev/dedup.py`: the Stage 5.5 `PAIR_QUESTION` on pairs inside each embedding group
  (`group_similar` at `dedup_threshold`) and the same star grouping. Display title: the
  keeper's `enriched_title`, else the first member's `enriched_title`, else the keeper's
  `title`. Results take the shape of `_run_llm_dedup`'s, with
  `_MergeAction(merged_text=<display title>, indices=<1-based positions in group_ids>)`, so
  `_apply_merge` and `_update_pipeline_state` are reused.
- `Deduplicate.execute` (`recap/tasks/deduplicate.py:229`) calls it instead of
  `_run_llm_dedup`, with the LLM path as fallback on `JevUnavailable`.
- `bench_jev.py dedup`: parse `dedup-N/input/task_prompt.txt` (`=== CLUSTER N (k articles) ===`,
  lines `n: [source] headline`) and the stdout (`MERGED:` + number line, `SINGLE: n`); pairwise
  co-membership precision/recall vs Gemini's groups; judge disputed pairs; sweep the threshold.
  Gate: judged correct ≥ Gemini's. The earlier experiment measured 90.2% pair agreement at 0.5
  (144k tokens for 399 pairs).
