# Plan: Per-Item Decisions on Jev, Writing on the LLM

Status: Stages 0–3, 5 and 5b done. Stage 4 (routing) failed on 2026-10-06, so the restructure
is dropped and Stage 5 became duplicate detection on Jev (the former Fallback B). Stage 5's
merges alone hid more stories than today's dedup, so Stage 5b writes the merged headlines with
one agy launch, as today's dedup does. Jev is opt-in per step (Decision 10); the author's
machine runs classify on Jev and dedup on the LLM. Next: Stage 7 after ≥ 14 nights. Related:
`plan-token-optimization.md` (its Phases 5–6, local clustering and the local classify cascade,
are superseded by Stages 3 and 5 here), issue #18 (Stage 0).

## Goal

A change ships only if it lowers agy token use or improves the digest, without making the other
worse. Two outcomes, each measured against a baseline recorded under *Evidence*:

1. **A digest every night.** Baseline: 21 of 32 nights (2026-09-04 … 10-05).
2. **Fewer agy tokens per night, digest no worse.** Baseline: 629k agy tokens on 10-06 (≈515k
   after Stage 3). Quality gates per step: no more wrongly dropped stories, no more wrongly merged
   ones, and duplicates removed at least as reliably as today.

Means: TypeSafe's Jev takes over the per-item *decisions* it was measured to make at least as
well as the LLM: exclude / vague (Stage 3) and "same piece of news?" (Stage 5). A Jev request
costs ~\$0.00003, answers every item and returns probabilities, but cannot write; agy keeps
enriching headlines, writing merged headlines, blocks and sections, merging per-batch sections
and refining the layout. Moving section placement to Jev was tested in Stage 4 and rejected: it splits about three
stories a night across two sections.

## Evidence (measured 2026-10-05)

### Nightly runs, 2026-09-04 … 2026-10-05

| Cause | Nights |
|---|---|
| agy quota — 4 lockouts: daily 09-10; weekly 09-16, 09-22/23, 10-01/02 | 6 |
| `load_resources` failure-rate gate (09-07, 09-27, 10-04) — issue #18 | 3 |
| `claude: agent exit code 1` (09-24, 09-25, not investigated) | 2 |

Every log ends with `RESULT: OK`: `recap_flow` catches `RecapPipelineError`, so `create`
exits 0 on a failed pipeline.

### agy tokens per step (night 2026-10-06, 412 kept articles)

The only archived night with token telemetry (Stage 0.5):

| Step | Launches | Tokens |
|---|---|---|
| classify (on Jev since Stage 3) | 3 | 126,718 |
| dedup | 6 | 157,484 |
| enrich | 3 | 123,312 |
| oneshot_digest | 3 | 170,614 |
| merge_sections | 1 | 17,869 |
| refine_layout | 1 | 33,008 |
| total | 17 | 629,005 |

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
classify (Jev) → load_resources → enrich (LLM) → deduplicate (Jev) → oneshot_digest (LLM)
  → merge_sections (LLM) → refine_layout (LLM)
```

- **classify** — Jev: exclude via one Noul per policy topic, vague via one Noul (Stage 3).
- **deduplicate** — the embedding pre-filter stays; Jev answers "same piece of news?" for every
  pair inside each candidate group, plus a wider net of pairs just below the pre-filter, instead
  of an agy launch per batch of clusters (Stage 5); one agy launch then writes the headline of
  every merged group (Stage 5b).
- Everything else is unchanged.

agy on 10-06: 17 launches / 629k tokens before Stage 3, 14 / ≈515k after it, 9 / ≈391k after
Stage 5b (dedup headlines 1, enrich 3, oneshot_digest 3, merge_sections, refine_layout), counting
≈13k more enrich tokens for Jev's extra vague headlines and 33k for the headline launch. On the
median night: 12 → 9 → 6.

## Decisions

1. **Use `typesafe-sdk` directly**, not the `jev` wrapper: `jev` requires Python ≥ 3.14 and
   discards the probabilities the thresholds need.
2. **Key lookup**, first hit wins: env `TYPESAFE_API_KEY` → `./.env` → `<data_dir>/.env`; a blank
   value falls through. Read with `dotenv_values()`, never written to `os.environ`.
   `TYPESAFE_API_KEY` is always stripped from agent subprocess env (agents read untrusted news
   text with permissions skipped). Every other setting, the Jev backends included, lives in
   `<data_dir>/config.toml` (`plan-config-toml.md`).
3. **Pinned model** `jev-1.13.0`; thresholds are tuned against it. Upgrading = rerun the bench,
   then bump.
4. **Thresholds are module constants**, set from the bench.
5. **Jev failure:** SDK retries, then `JevUnavailableError`; the step logs a warning and reruns
   on its LLM path. The LLM paths stay: they are the defaults (Decision 10).
6. **Merged headline.** Today's LLM dedup writes a new headline for each merged group that keeps
   the facts of all members. Jev cannot write, so after Jev picks the groups one agy launch
   writes every group's headline from all its members (Stage 5b). A group that launch leaves
   without a headline stays unmerged: a duplicate left visible is the lesser harm (Decision 8),
   as when one of today's dedup launches fails.
7. **Gates compare Jev with today's LLM on the same items**: the reader-visible errors a step
   can cause (wrong excludes, wrong merges) must not increase and its correct decisions must not
   decrease; a gate that requires more says so. Ground truth is labels made blind by Claude
   (`labeler: claude-opus-5-5`) at the user's request, under written rules: the user confirmed
   the classify rules (Stage 1.2); the dedup rule (Stage 5) awaits the user's confirmation. The
   Sonnet judge is used only for tasks where its agreement with the labels has been measured.
8. **A wrongly excluded story is worse than a wrongly kept one** (the reader never sees it), so
   wrong excludes are gated separately.
9. **Bench data** lives in `~/.news_recap_data/bench/`. Only the rows a spec sentence relies on
   are committed (`bench/` in the repo, with a README naming the claim each file supports).
10. **Jev is opt-in per step.** `classify_backend` and `dedup_backend` in `config.toml`
    default to `llm` with or without a key, so a fresh install runs with no keys at all on the
    free agy tier; the docs' quick start shows that path first and Jev as an option.

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
(`gc_retention_days`), so until Stage 5 ends run `bench_jev.py snapshot` (Stage 1) at least
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
`snapshot | label | judge-check | classify | route | dedup`.
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

**Done 2026-10-06** (`recap/jev/`, tests in `tests/recap/jev/`, `tests/test_config.py`,
`tests/recap/agents/test_ai_agent_env.py`, `tests/recap/storage/test_pipeline_io.py`,
`tests/test_launcher.py`). Live smoke test: 2 requests, 577 input tokens; a bad key raises
`JevUnavailableError` (401). Differences from the bullets below:

- `JevSettings` holds only `api_key` (`repr=False`), `model` and the per-step backends. Steps run
  from `pipeline_input.json`, not `Settings`, so concurrency and price could never reach them
  from there: `MAX_CONCURRENCY = 16` is a constant in `jev/client.py`, `PRICE_PER_MTOK = 0.042`
  in `jev/usage.py`, and `save_jev_usage` has no `price_per_mtok` argument.
- `JevUnavailable` is named `JevUnavailableError` (ruff N818, same as the other exceptions).
- The per-step backends are `classify_backend` / `dedup_backend` in `config.toml`, not the
  `NEWS_RECAP_*_BACKEND` variables of the bullets below (`plan-config-toml.md`).
- The key lookup is `config.resolve_typesafe_api_key(data_dir)`, shared by `Settings.load`
  and `make_jev_client`. An empty value falls through to the next source.
- `jev_task_dir(pipeline_dir, step)` names the `<step>-jev` workdir.
- `TYPESAFE_API_KEY` is popped after `extra_env` is merged, so no task-map env can re-add it.
- `jev_model` and `classify_backend` are written when the pipeline is created and are not
  refreshed on resume (a resumed night keeps its backend).
- `JevClient.decide` runs requests in an `asyncio.TaskGroup`: the first SDK error cancels the
  rest. Tokens are counted per completed request, so a failed batch still reports what was
  billed.
- The stage table has no cost column yet. Stage 3 adds one (from `cost_usd`) so the
  *Verification* check "a `classify-jev` row with tokens and cost" can pass.

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
  - `class JevUnavailableError(RecapPipelineError)`
  - `class JevClient` wrapping `AsyncTypeSafeClient`, with
    `decide(requests: list[tuple[JSONContent, dict[str, Question]]]) -> list[SystemOneResponse]`.
    It runs `asyncio.run` with a semaphore of `max_concurrency` and accumulates `input_tokens`
    and request count. It maps `TypeSafeError` and its subclasses (auth, rate-limit after SDK
    retries, timeout, connection) to `JevUnavailableError`.
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
    strip, drop empties (doctests). Used by classify and the Stage 4 bench.

Tests:

- key lookup precedence (env > cwd `.env` > data-dir `.env`);
- the key never appears in `os.environ`;
- `TYPESAFE_API_KEY` is absent from the agent env even when set in the process env;
- backend parsing and validation, including the no-key downgrade;
- `JevClient` error mapping with a fake async client;
- `save_jev_usage` round-trips through `read_agent_usage`.

## Stage 3 — Classify on Jev (~1 day + bench)

**Done 2026-10-06: gate passed** (`recap/jev/classify.py`, `Classify._classify_on_jev`,
`bench_jev.py classify`; tests in `tests/recap/jev/test_classify.py`, `tests/test_bench_jev.py`,
`tests/test_config.py`, `tests/test_cli_output.py`). Classify on Jev is opt-in:
`news-recap config set classify_backend jev` (Decision 10). Bench rows: `bench/classify-2026-10-06.jsonl`.

Results (exclude ≥ 0.75, vague ≥ 0.65, `full` state; every Jev/Gemini disagreement labelled,
unlabelled agreements count as correct):

| | wrong excludes (Jev / Gemini) | missed excludes | correct exclude/keep | vague F1 |
|---|---|---|---|---|
| tuning, 1 459 headlines | 4 / 13 | 6 / 12 | 1 449 / 1 434 | 0.526 / 0.525 |
| holdout, 277 headlines | 0 / 0 | 4 / 6 | 273 / 271 | 0.629 / 0.629 |

- Cost: 371–387k tokens per tuning night (~785 per headline) → \$0.48/month; holdout night
  216k. Bench spend: \$0.15 (3 variants × tuning nights + holdout).
- Exclude improves; vague only ties Gemini (both weak: F1 0.53 on tuning).
- Jev calls more headlines vague (113 vs 98 on the four nights; 32 vs 16 on 10-01), and each
  vague headline is rewritten by enrich (≈3.2k agy tokens per article on 10-06): about 13k of
  the 127k classify saving on an average night, up to ≈50k.
- Threshold curves (tuning, `full`): exclude 0.65 → 27 wrong / 2 missed, 0.70 → 7 / 5,
  0.75 → 4 / 6, 0.80 → 3 / 10 (+23 unlabelled). Vague F1 0.50 / 0.53 / 0.53 / 0.50 at
  0.55 / 0.60 / 0.65 / 0.70. 0.75 is the fewest wrong excludes among the best exclude/keep
  totals (Decision 8); 0.65 is mid-plateau with higher precision than 0.60 (fewer enrich
  rewrites). Chosen on tuning nights before the holdout run.
- State variants: `no_source` at 0.70 ties `full` at 0.75 on exclude; vague from a separate
  `headline_only` request reaches F1 0.56 but doubles tokens (\$0.93/month): a headline-only
  request still costs 91% of a `full` one, because the six questions dominate. Not adopted.
- Labels: 126 more (119 tuning, 7 holdout), again by Claude (`labeler: claude-opus-5-5`), blind,
  under the Stage 1.2 rules; 348 in total.
- Live check in a scratch copy of the data dir: `create --from 2026-10-05 --limit 300
  --stop-after classify` with no backend variable → 300 articles in 5 s, `classify-jev` row
  with 233,766 tokens and \$0.0098, no `classify-N` dirs; 29 excluded (27 Croatian domestic or
  Croatian sports), 14 vague.

Differences from the bullets below:

- `verdict` takes the thresholds as optional arguments (the bench sweeps them);
  `policy_questions(policy)` builds the `t0…tN` + `vague` questions.
- The Jev path also falls back to the LLM when no key is found at run time, and writes
  `classify-jev/meta/usage.json` even when Jev fails, so billed tokens are recorded. A fallback
  logs `classify: Jev unavailable (…) — classifying with the LLM`; Stage 7 counts that line in
  the nightly logs.
- `bench_jev.py classify` sweeps (exclude state, exclude threshold, vague state, vague
  threshold) in 0.05 steps, so a configuration may take vague from another state's request.
  Runs are stored once per (variant, model) and reused; `--holdout` scores the module constants
  on the holdout night, `--config ev:te:vv:tv` scores one configuration. Unlabelled
  disagreements of the top configurations go to `bench/labels/pending-classify.jsonl` for
  `label --items`.
- The stage table gains a Cost column, shown only when a step reports `cost_usd`.
- Tests run against a temporary data directory (autouse fixture), so a developer's key or
  `config.toml` never reaches them.

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
`JevUnavailableError`, log a warning and run the existing batch flow. The 80% recognition guard does
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

**Done 2026-10-06: gate failed (split rate); routing is dropped.** The user chose Fallback B
(now Stage 5) after a comparison against today's pipeline: the restructure would save 51k more
agy tokens a night than Fallback B (208k vs 157k of today's 502k) at the cost of about three
stories a night shown in two sections. The bench stays (`bench_jev.py route`, with the routing
code inside the script; tests in `tests/test_bench_jev.py`) so the numbers below reproduce.
Labels by Claude (`labeler: claude-opus-5-5`): `bench/labels/route.jsonl` (53 follow
disagreements) and `bench/labels/route-splits.jsonl` (54 split blocks). Bench rows:
`bench/route-2026-10-06.jsonl`.

Results, chosen configuration (follow ≥ 0.30, confidence ≥ 0.40, `url` state); tuning = every
archived night except the holdout (09-29, 09-30, 10-01, 10-06):

| | split blocks | other share | follow disagreements: Jev right / LLM right |
|---|---|---|---|
| tuning, 1 519 articles, 227 multi-article blocks | 47 (20.7%) ❌ | 2.2% | 15 / 14 of 16 |
| holdout, 239 articles, 32 blocks | 7 (21.9%) ❌ | 4.6% | 1 / 1 of 2 |

- Follow placement agrees with today's digests on tuning nights: Serbia 365/366 LLM→Jev and
  365/371 Jev→LLM, Russia 69/69 and 69/76, war in Ukraine 28/30 both ways.
- Of the 54 split blocks, 43 separate different stories that today's LLM bundled by theme
  (DoorDash drones + FedEx trucks); 11 (4.2% of 259 blocks) put one news event in two sections
  (French student protests in Society and in International politics; BMW pricing in Economy and
  in other).
- Cost: ≈ 311k tokens per tuning night → \$0.39/month; bench spend ≈ \$0.15.

Differences from the bullets below:

- **Follow topics are Nouls, not Choice options.** With one Choice over all sections the split
  rate was 30.8%: Choice probabilities are exclusive and peaked (a Serbian tender → "Economy"
  p≈1.0, Serbia ≈0), so `FOLLOW_THRESHOLD` never fired. One Noul per follow topic ("is this story
  mainly about …?") plus a Choice over general sections + other.
- **The URL is in the state.** 94–165 articles a night (021.rs, tanjug.rs) have no text; their
  URL carries the outlet's own section (`srbija/hronika`, `info/region-i-svet`). Serbia
  agreement 360/366 → 365/366 for +7% tokens.
- "Science, climate and nature" became "Science and nature (research, medicine, climate,
  environment, wildlife)": the `sections` comma syntax would split the first name in two.
- The plan's split remedy does not work: with the pipeline's embedder (multilingual-e5-small)
  connected components at 0.65–0.80 swallow each whole night; at 0.90 they chain unrelated
  stories and the split rate rises (22.5%).
- Labels replace the judge for follow disagreements (as in Stage 3), and the 20-item user
  spot-check was not needed. Two boundaries are labelled "either placement" and tagged
  (`boundary`): Kosovo stories and Republika Srpska / BiH elections; the follow gate passes under
  every reading of them.

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
- Still failing → Fallback B (now Stage 5).

## Stage 5 — Duplicate detection on Jev (former Fallback B; ~1 day + bench)

**Built 2026-10-06; the pair gate passed but the reader-visible one failed** (`recap/jev/dedup.py`, `Deduplicate._dedup_on_jev`,
`dedup_backend`, `bench_jev.py dedup [--wide]`; tests in `tests/recap/jev/test_dedup.py`,
`tests/test_bench_jev.py`, `tests/test_config.py`, `tests/recap/storage/test_pipeline_io.py`).
Dedup on Jev is opt-in: `news-recap config set dedup_backend jev` (Decision 10). Labels: 319 pairs by Claude
(`labeler: claude-opus-5-5`). Bench rows: `bench/dedup-2026-10-06.jsonl`.

Results (headline state, the "news" question below; candidate groups merge at ≥ 0.40, the wider
net at ≥ 0.70; every Jev/Gemini disagreement labelled, unlabelled agreements count as correct):

| | candidate pairs | wrong merges (Jev / Gemini) | missed duplicates | correct pairs |
|---|---|---|---|---|
| tuning, 4 nights | 1 569 | 13 / 31 | 25 / 8 | 1 531 / 1 530 |
| holdout | 85 | 1 / 2 | 1 / 1 | 83 / 82 |

- The numbers are in-sample: the question, the labelling rule and both thresholds were chosen
  on the tuning nights' labels. The holdout (85 pairs) is too small to separate the two.
- **Wrong merges are not equally visible to the reader.** Today's LLM writes the merged
  headline, and in 15 of its 16 wrongly merged groups that headline still states both stories
  ("Nvidia unveiled an AI-agent safety platform and announced a record buyback"); only one
  reaction is lost ("Spaniards welcome snap election"). A Jev merge shows one existing title, so
  its wrong merge hides the other story (OpenAI's office suite under OpenAI's app-store story).
  Most of Jev's wrongly merged pairs are reports of one event at different moments or two
  speeches by one person. In articles, with the 0.85–0.90 wider net: on the tuning nights Jev
  removes 151 true duplicates (Gemini 132) and 9 different stories (Gemini 17), and every one of
  Jev's 9 disappears from the digest, where 15 of Gemini's 16 groups keep the story in the merged
  headline; on the holdout, 9 / 7 duplicates and 2 / 2 different stories (both of Gemini's kept in
  its headline). Stage 5b closes the gap.
- **The duplicate gain comes from the wider net.** Inside today's candidate groups alone Jev
  removes fewer true duplicates than today: 123 vs 132 on the tuning nights, 7 vs 7 on the
  holdout.
- Wider net, first measured at similarity 0.85–0.90 (outside today's candidate groups, which
  today's pipeline never examines): Jev says "same" for 46 pairs on the tuning nights, 43 labelled same (93%), and 5 on
  the holdout, 4 same; 47 of 51 (92%, 95% interval 81–97%) overall, above the 90% bar. The holdout
  alone (4 of 5) is too small to decide, so Stage 7 checks it on new nights. Star grouping merges
  an outsider only when it matches the group's keeper, so on the tuning nights these pairs remove
  30 articles (28 duplicates, 2 different stories), ≈ 7 duplicates a night; a translation that
  matches only a non-keeper member stays (Starship's orbit in Serbian on 09-29). Typical catches are
  translations and paraphrases: Starship's first orbit in Serbian and English, the Kyiv academy
  strike in Croatian and English, the Vučić → Brnabić handover reports.
- **Shipped band: 0.87–0.90** (`WIDE_SIMILARITY`). The 0.85–0.87 band is 74% of the wider net's
  requests for 22 of its 47 true merges. At 0.87: Jev's "same" pairs are 22 of 24 labelled same
  on the tuning nights and 3 of 3 on the holdout; Jev removes 138 true duplicates and 9 different
  stories on the tuning nights (today 132 / 17; +15 from the wider net) and 9 / 1 on the holdout
  (today 7 / 2). Requests on 10-06 ≈ 1 200 instead of 3 576, ≈ \$0.74/month instead of \$2.2
  (scaled from the bench's band counts, not a live run). Narrower bands: 0.88 → 133 true
  duplicates, \$0.44; no wider net → 123, below today.
- Live check at the 0.85 band on a copy of night 10-06 (real embedder, real Jev, no agy): 452 articles → 410
  (today's LLM dedup removed 40 that night), 3 576 pair requests (389 candidate + 3 187 wider),
  1.72M tokens, \$0.072, 72 s (61 requests/s at 16 concurrent). Jev for dedup ≈ \$2.2/month; agy
  −6 launches / −157k tokens on that night. 12 of its 13 wider-net merges are labelled same.
- The bench builds the wider net from the archived original titles, while production embeds
  enriched titles at dedup time, so the bench selects fewer wider pairs (2 688 vs 3 187 on
  10-06). Precision is unaffected (above); cost figures come from the live run.
- Bench spend ≈ \$0.45 (all Stage 5 runs).

Differences from the bullets below:

- **The question.** The plan's "same specific news event" Noul made 61 errors where Gemini made
  23 (at that point of labelling): it merged separate statements about one story (the opposition's
  and the government's reactions to the Šapić incident, a death and the condolences) and split one
  incident reported at different moments (a Starship live stream and the orbit reports). The
  production question asks whether one item could replace the other "without the reader losing
  an important fact", with yes/no criteria stating the rule. The headline-only state beats
  headline + source + lead with this question.
- Labelling rule: same = one event or announcement reported twice, including the same incident at
  different moments, live coverage and later reports, eyewitness accounts, and one statement
  carried by several outlets; different = separate events, or a separate statement, reaction,
  denial or official assessment, an analysis, explainer or interview, or a roundup covering
  several stories (Reuters' "World News" videos).
- Two thresholds, `SAME_EVENT_THRESHOLD` 0.40 and `WIDE_THRESHOLD` 0.70: below the pre-filter,
  pairs are more often different stories. The 0.80–0.85 band (5–18k pairs a night) was not tried.
- Merge groups are connected components of "same" pairs, star-grouped inside (keeper = longest
  text), so a wider-net pair can join a candidate group.
- Not covered, as today: `group_similar` splits a candidate group above 20 articles into chunks,
  and pairs at similarity ≥ 0.90 across those chunks are never asked (5–8 pairs a night on the
  bench nights).
- No full `create --stop-after deduplicate` run: it needs enrich, i.e. agy launches. The first
  nightly run with `dedup_backend = "jev"` is the end-to-end check.

Today: `group_similar` builds candidate groups (connected components at embedding similarity
≥ `dedup_threshold` 0.90 over title + text), then 3–6 agy launches a night answer `MERGED` /
`SINGLE` per cluster and write a merged headline (157k tokens on 10-06).

5.1 `recap/jev/dedup.py`:

- `PAIR_QUESTION` Noul: "Do article_a and article_b report the same specific news event, so a
  reader would consider them the same piece of news (not merely related stories)?"; state
  `{headline_a, headline_b}` (enriched title when present). Bench variant `lead` adds
  `lead_a`, `lead_b` (first 300 chars of text).
- `SAME_EVENT_THRESHOLD` from the bench (the 2026-10-05 experiment: 90.2% pair agreement with
  Gemini at 0.5, 144k tokens for 399 pairs).
- `star_groups(ids, same) -> list[list[str]]`: ids sorted by `len(clean_text)` descending; each
  joins the first group whose keeper it matches at ≥ the threshold, else starts a new group; only
  groups of ≥ 2 are returned. No chaining: A≈B, B≈C, A≉C → C does not join A's group.
- `dedup_groups(client, groups, id_to_article, threshold)`: one request per pair inside each
  candidate group; returns the merge groups and per-pair probabilities.

5.2 `Deduplicate.execute` (`recap/tasks/deduplicate.py`): when `dedup_backend == "jev"`, turn
each merge group into `_MergeAction(merged_text=<Decision 6 title>, indices=<1-based positions in
the merge group>)` (the merge group, not the candidate group: a wider-net pair can join groups),
so `_apply_merge` and `_update_pipeline_state` are reused; `_apply_merge` leaves the keeper's
`enriched_title` unset when the Decision 6 title is its own original title, so a resumed enrich
still rewrites a vague keeper;
write `dedup-jev/meta/usage.json` (also when Jev fails) and `output/jev_answers.json`. On
`JevUnavailableError` or a missing key at run time: warning, then the LLM path.

5.3 Settings: `NEWS_RECAP_DEDUP_BACKEND=llm|jev`, parsed like the classify backend (no key →
`llm` with a warning); `PipelineInput.dedup_backend`. Default `llm` until the gate passes, then
`jev` when a key is found. `tests/conftest.py` pins `llm`.

5.4 `bench_jev.py dedup`:

- replay Gemini's decisions from the archived `dedup-N` workdirs: single-cluster prompts
  (`=== NEWS (k total) ===`) and multi-cluster prompts (`=== CLUSTER N (k articles) ===`), lines
  `n: [source] headline`; stdout `MERGED:` + a numbers line, `SINGLE: n`, `CLUSTER N:` headers.
  A pair is "merged by Gemini" when both articles sit in one `MERGED` group;
- Jev probabilities per pair and state variant in `bench/runs/dedup-<variant>-<date>.jsonl`;
- sweep the threshold 0.30 … 0.90; apply `star_groups` per cluster, so the scored decision is
  what the pipeline would merge; score pairwise co-membership against Gemini's;
- label every disputed pair (`bench/labels/dedup.jsonl`: `same` | `different`), blind;
- gate, on tuning nights and on the holdout separately: Jev's wrong merges (merged, label
  `different`) ≤ Gemini's, and Jev's correct pair decisions ≥ Gemini's; unlabelled agreements
  count as correct;
- wider net (a quality gain today's launches cannot afford): pairs today never examines
  (similarity 0.80–0.90, no chaining). Jev-merged pairs among them are labelled; the wider net
  ships only if ≥ 90% of its added merges are labelled `same`.

5.5 Tests: star grouping (no chaining, keeper = longest text), display title order, the Jev
path producing `_MergeAction`s, fallback on `JevUnavailableError`, backend parsing; bench replay
parser and gate.

## Stage 5b — Merged headlines on the LLM (~0.5 day + one agy launch per bench night)

**Done 2026-10-06: gate passed** (`deduplicate.write_merged_titles`, `RECAP_DEDUP_TITLES_PROMPT`,
`jev.dedup.merges_from`, `bench_jev.py dedup-titles`; tests in `tests/recap/jev/test_dedup.py`,
`tests/test_bench_jev.py`). Bench rows: `bench/dedup-titles-2026-10-06.jsonl`.

Results (one agy `gemini-3.7-flash --effort low` launch per tuning night, on the merge groups
the pipeline makes from the stored Stage 5 probabilities):

- 123 groups, every one with a headline (none kept a Decision 6 title), all in Russian; median
  length 1.16 × the longest original, 10 groups above 1.5 ×.
- Of the 9 members labelled `different` from their keeper, 8 are stated in the written headline
  ("OpenAI expanded ChatGPT with apps, automation and an office suite, challenging the App Store
  and Microsoft"). One is lost: a review of the AI Greta Garbo advert, an opinion piece. Today's
  dedup also loses one (the "Spaniards welcome snap election" reaction).
- 25.8–33.0k agy tokens per launch (20–28k input, about 13k of it the per-launch overhead;
  3.6–5.8k output including thinking), ≈ 20 s.
- The holdout night was not run (one more launch); Stage 7 reads new nights' merged groups.
- The gate ran on the 0.85–0.90 wider net's groups. At the shipped 0.87 band 8 of the 9 wrongly
  merged members sit in the same groups (7 stated, the Greta Garbo review lost); the ninth
  (Reuters' FlyDubai explainer) is in a group that lost one same-story member, and its headline
  was not re-measured, to spare agy launches in a week already near the lockout level.

Stage 5's merges keep one existing title, so a wrong merge hides the other story; today's LLM
rewrites the merged headline and keeps it (15 of its 16 wrong groups). Stage 5b keeps Jev's
groups and gives each one an LLM headline again, in one launch for the whole night.

- `Deduplicate._dedup_on_jev`: after `find_duplicates`, one `recap_dedup` launch (same model and
  timeout as today's dedup) gets every merge group as `=== GROUP N ===` with `n: [source] title`
  lines and answers `GROUP N: <headline>` per group, under today's rules (keep the key facts of
  all members, a separate fact, statement or reaction included; not much longer than the longest
  original; output language). A failed launch, or a group the launch leaves without a headline,
  leaves that group unmerged (Decision 6). Merge groups are emitted in a fixed order (by smallest
  article id).
- Gate (Claude reads every group with a member labelled `different` from its keeper, on the four
  tuning nights): stories whose fact is missing from the written headline ≤ today's (1, the
  "Spaniards welcome snap election" reaction); every group gets a headline in the output
  language.
- Pass → dedup on Jev can be turned on (`dedup_backend = "jev"`). Fail → it stays off.

## Stage 6 — dropped

The side-by-side week tested the restructure, which Stage 4 rejected. Stage 5 is gated on
labelled pairs, like Stage 3.

## Stage 7 — Docs and cleanup (~0.5 day)

- `spec/pipeline.md`:
  - per-step contracts for classify (Jev) and deduplicate (Jev);
  - the Cost section rewritten (agy launches and tokens per night, Jev \$/month);
  - bench conclusions under Experiments, citing the committed `bench/` rows, including why
    section routing on Jev was rejected (Stage 4).
- `spec/plan-token-optimization.md`: mark Phases 5–6 superseded by this plan.
- `bench/README.md`: each committed run file and the spec sentence relying on it. A run stays
  only while a claim rests on it.
- Record the observed Jev failure rate (fallbacks to the LLM) in `spec/pipeline.md`.
- Once dedup on Jev runs nightly, a wider-net check on new nights: label every wider-net merge (`wide` and `same` in
  `dedup-jev/output/jev_answers.json`) of the first 7 nightly runs. Keep the wider net if ≥ 90%
  are the same piece of news; otherwise raise `WIDE_THRESHOLD` to the lowest value that reaches
  90% on them. On the same nights, read every merged group with a separate story and check that
  its written headline states it (Stage 5b's gate on new data).
- agy tokens per night are `total_tokens` in `digests.json` (agents only); Jev is recorded apart
  in `jev_tokens` and `jev_cost_usd`. Goal 2 is checked on these.

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
uv run python scripts/bench_jev.py route          # Stage 4 (rejected; reproduces the numbers)
uv run python scripts/bench_jev.py dedup          # Stage 5
uv run python scripts/bench_jev.py dedup-titles   # Stage 5b — one agy launch per night
news-recap config set classify_backend jev && news-recap create --stop-after classify
news-recap config set dedup_backend jev && news-recap create --stop-after deduplicate
```

The classify command shows a `classify-jev` row with tokens and cost and creates no `classify-N`
workdirs; the dedup command shows a `dedup-jev` row and a single `dedup-N` workdir, the merged
headlines launch.

Manual, once: put `TYPESAFE_API_KEY` into `~/.news_recap_data/.env` so the scheduled job
(launchd starts it with cwd `/`) finds it; the backends are in `~/.news_recap_data/config.toml`.

## Expected impact

agy figures are the 10-06 night (412 articles); Jev from the bench.

| After | agy launches / tokens | Jev \$/month | Measured quality change |
|---|---|---|---|
| Stage 0 | 17 / 629k | 0 | nights lost to `load_resources`: 3/32 → 0 |
| Stage 3 (classify on Jev) | 14 / ≈515k | ≈ 0.48 | wrong excludes 4 vs 13 (tuning), 0 vs 0 (holdout); ≈ 4 more vague headlines a night, ≈ 13k more enrich tokens |
| Stage 5 + 5b (dedup on Jev, 0.87 band) | 9 / ≈391k | ≈ 0.48 + 0.74 | stories lost from merged headlines 1 vs today's 1 (gated at the 0.85 band); true duplicates removed 138 vs 132 (4 tuning nights, in-sample), +15 of them from the wider net; merged headlines written in the output language, as today |

## Risks

- **A wrong merge hides a story** (the reader sees one headline for two events): the Stage 5b
  headline states the merged-in story; its gate counts stories missing from it, like wrong
  excludes (Decision 8).
- **A failed headline launch** leaves that night's Jev groups unmerged (Decision 6): about 40
  duplicates stay visible, nothing is hidden, as when one of today's dedup launches fails.
- **A Jev outage** falls back to the LLM for that night (Decision 5).
- **Rate limits** are "adjusting dynamically": SDK retries; the 10-06 live run reached 61 req/s
  at 16 concurrent requests against the documented 80 req/s. One request that still fails after
  the retries sends the whole step to its LLM path.
- **Catch-up nights**: the wider net grows with the square of the night's size (at 0.85–0.90:
  277 articles → 1 320 pairs, 452 → 3 187; the 0.87 band asks about a quarter of those); it is
  capped at the 5 000 most similar pairs (≈ 80 s, ≈ \$0.10).
- **Free-text policies are read literally**: docs tell users to phrase topics as subjects.
- **The `jev-latest` alias moves**: the model is pinned (Decision 3).
