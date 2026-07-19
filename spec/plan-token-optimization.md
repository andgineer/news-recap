# Plan: Token Usage Reduction (CLI Backend)

Status: proposed. Companion plan: `plan-agent-sandboxing.md` (its Phase 0 overlaps
with Phase 1 here — the slimmed claude template serves both goals). That plan's
*Backend priority* asserts agy "is the default and must stay the default" — today that is
aspirational: the **code** default is codex. **Phase 0 here performs the actual switch**,
making the assertion true. **Both plans retain
file-based prompt delivery — stdin proved unstable (see the Phase 1 finding); the claude
launch is slimmed while it keeps its `Read` tool to read `{prompt_file}`, and results are
still captured from stdout.**

Billing model — **every backend has a hard consumption budget; none is "cost-free," and
consumption economy matters for _all_ of them.** The pipeline's *intended* default backend
is antigravity (`agy`), which needs no paid subscription — but **today the code default is
still codex** (`config.py:141`, `default_agent = "codex"`; `spec/agents.md` documents the
same), so "agy is the default" holds only for deployments that set
`NEWS_RECAP_LLM_DEFAULT_AGENT=antigravity` by hand. Phase 0 makes agy the real code
default. agy's free tier is capped by both
**requests-per-day and a token budget**. Exhausting it does not merely throttle — it
**locks the account out for a day, and up to 7 days on the weekly cap** (the free Gemini
Flash allowance has been as low as ~20 requests/day; quotas reset on 5-hour / daily /
weekly cycles — see Sources at the end). Because a single pipeline run already fires 10–40
CLI launches, agy's budget is the *tightest* constraint of all, not a non-issue. **claude**
and **codex** are optional quality-tier backends; there "cost" = subscription **quota**
consumption, measured in tokens with provider-side cache discounts. The API backend stays
experiment-only.

There are two distinct levers, and every backend feels at least one:

- **Per-launch overhead** (Phase 1) — token-weighted. Hits claude/codex token quota
  directly, and any token-metered part of agy's budget. Slim it for agy too (Phase 1
  item 5), not only for claude.
- **Launch count + payload size** (Phases 4–5) — hits agy's per-day/per-week **request
  cap** (the binding constraint there) and every backend's token spend. (Phase 3's audit
  found the retry-coalescing lever already implemented — see that phase.)

Goal: cut consumption substantially, across all backends, without a measurable quality drop.

## Measured baseline (research done 2026-07-13, claude CLI, live calls)

| Launch mode | Input tokens for a 10-token prompt |
|---|---|
| Default `claude -p` | **24 378** (24 368 system prompt + tool schemas, cached-write) |
| `claude -p --tools "" --system-prompt "…" --setting-sources ""`, prompt on stdin | **167** |
| Slimmed **file-delivery** mode (`--allowed-tools "Read" --system-prompt "…" --setting-sources ""`, prompt read from `{prompt_file}`) | **to be measured** — above 167 (keeps the `Read` tool schema + agentic harness), still well under 24 378 |

**Finding — stdin is not viable; file delivery is retained.** The 167-token row above
used stdin + `--tools ""`. Experiments and upstream reports show stdin delivery is
unreliable at production sizes: `claude -p` returns **empty output** once piped stdin
exceeds a few KB (anthropics/claude-code#7263) while our prompts reach 60 KB (enrich);
`agy -p` silently drops stdout under a subprocess; `codex exec` hangs on EOF with a
non-TTY pipe. So this plan **keeps file-based delivery** and slims the launch *without*
going tool-less: strip the default system prompt and settings, and narrow tools to the
single `Read` needed to read `{prompt_file}`. The saving is therefore smaller than the
tool-less 167 and **must be re-measured** — the `Read` tool schema and the agentic
system prompt stay in context.

Two further verified facts:

- `--output-format json` returns a single-object envelope with
  `result` (the text) and `usage` (`input_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `output_tokens`) plus `modelUsage` and
  `total_cost_usd` — full per-call telemetry that text mode does not provide. This is
  **optional and independent of prompt delivery**; it does not change the file-based
  flow and is used only for telemetry (Phase 2).
- Caveat: `--bare` mode must NOT be used — it restricts auth to `ANTHROPIC_API_KEY`
  (OAuth subscription auth is never read), which defeats the subscription model.

Implication (claude tier): with the current pipeline shape (typically 10–40 CLI launches
per run: classify batches + enrich batches × up to 3 retry rounds + dedup batches +
oneshot batches + merge + refine), **claude launch overhead alone is ~0.25–1.0 M input
tokens per day** — very likely the single largest line item on the claude quota, ahead of
any payload. **Caveat — this is a raw upper bound, not the billed figure.** The 24 378
baseline is a cache-*write* number; if the system-prompt+tools prefix is byte-identical
across launches in a run, provider caching amortizes it as cache-*reads* at a steep
discount, so the *billed* overhead may already be well below 0.25–1.0 M. Phase 2 telemetry
(`cache_read_input_tokens`) settles this and, with it, the true size of the Phase 1 win.
Once agy is the code default (Phase 0), the pressure on it is twofold: its
**per-day/per-week request cap**
(relieved by fewer launches — Phases 4–5) and, wherever the budget is token-metered, the
same per-launch overhead (relieved by slimming agy's launch the way Phase 1 slims claude's
— Phase 1 item 5). "Free" means no invoice, **not** no budget: hit the cap and the account
is locked out for a day or more — with a run firing 10–40 launches against an allowance
that has been as low as ~20/day, that lockout is a routine failure mode, not an edge case.

## Phase 0 — Make antigravity the code default (~0.5 day)

The whole prioritization below assumes the free agy backend is what the pipeline runs on
by default. Today that is only an intention: the code default is codex (`config.py:141`,
`default_agent: str = "codex"`), and `spec/agents.md` documents codex too. The sandboxing
plan's *Backend priority* already *states* agy is the default — this phase makes the
statement true instead of aspirational. (Not to be confused with "Phase 0 of the
sandboxing plan", which is the slimmed claude template = Phase 1 item 1 here.)

1. `config.py`: `default_agent` `"codex"` → `"antigravity"`. The supporting maps already
   carry antigravity entries (`_default_task_model_map`, `_default_agent_max_parallel`
   with its parallelism-1 note, `agent_launch_delay`, `_DEFAULT_AGENT_API_KEY_VARS`), so
   the swap is one line plus tests.
2. `NEWS_RECAP_LLM_DEFAULT_AGENT` stays the opt-out: operators on codex/claude
   subscriptions set it explicitly; nothing else changes for them.
3. Tests: update the settings-default assertions; one smoke run with the echo/mock agent
   to confirm routing resolves antigravity end-to-end.
4. Docs: fix the `NEWS_RECAP_LLM_DEFAULT_AGENT` row in `spec/agents.md` (part of the
   larger agents.md rewrite — Phase 1 item 7) and the README if it names the default.

## Phase 1 — Slim claude launches, file delivery kept (~1–2 days)

Cut the ~24 k-token launch overhead as far as possible **without** giving up the
working file-based prompt delivery. The tool-less + stdin path (measured at 167 tokens)
is **rejected**: stdin is unreliable at our sizes (see the finding above). We keep
`{prompt_file}` and narrow everything else.

**Do item 1's re-measurement first, as a go/no-go — before writing any other Phase 1
code.** The whole plan is ordered on the assumption that the slimmed launch is *much*
cheaper than 24 k. That number is currently unmeasured, and two unknowns (below) could
make it far closer to 24 k than to 167. If the slimmed template comes back at, say,
8–12 k, Phase 1's ROI collapses and the fewer-launches / smaller-payload work (Phases
4–5) should move ahead of it. Measure, then commit to the order — it is a 30-minute
experiment that gates the rest.

1. New default claude template (config.py) — file delivery, minimal tools:

   ```
   claude -p {model} --setting-sources "" \
     --allowed-tools "Read" \
     --system-prompt "You are a text-processing engine. Follow the task instructions exactly. Reply with plain text only." \
     -- "Read your task from {prompt_file} and execute it."
   ```

   - `--allowed-tools "Read"` keeps the one tool needed to read the prompt file and drops
     every network/write tool (this is exactly Phase 0 of the sandboxing plan).
   - **No `--permission-mode`.** The sandboxing plan's live experiment proved
     `--allowed-tools "Read"` alone is *necessary and sufficient* headless — an
     allowlisted `Read` runs without a prompt, so `dontAsk`/`bypassPermissions` are
     unneeded (and are exfil/permission surface). Dropped here to keep the two plans'
     shared template byte-identical.
   - `--setting-sources ""` and a short `--system-prompt` strip the settings load and the
     default system prompt — the bulk of the 24 k overhead.
   - Prompt is **read from the file**, not piped. `run_subprocess` is unchanged
     (`stdin=subprocess.DEVNULL` stays); no stdin plumbing is added.
   - **Re-measure** input tokens for this template against a trivial prompt to record the
     real saving (expected: far below 24 k, above the tool-less 167). Two semantics decide
     whether the win is ~200 tokens or ~10 k — verify both explicitly, they are the crux:
     - **Does `--allowed-tools "Read"` drop the other tool *schemas* from context, or only
       auto-approve `Read` while every schema stays loaded?** The token saving from
       tool-narrowing is real only in the first case. Sandbox semantics (what is
       auto-approved) and context-cost semantics (which schemas load) are not necessarily
       the same thing; the baseline's "24 368 = system prompt + tool schemas" implies
       schemas are a large share, so confirm they actually leave.
     - **Does `--system-prompt` replace the whole system prompt, or does Claude Code keep a
       non-overridable harness preamble underneath it?** If a base preamble survives, the
       floor is much higher than the tool-less 167. This is the single largest driver of
       the final number.

2. Result retrieval is **unchanged**: the agent writes to stdout, the parent captures
   `output/agent_stdout.log`, and every parser in `tasks/` reads it via
   `read_agent_stdout`. No `--output-format json` rewrite is required for the default
   path.

3. **JSON telemetry (decoupled from delivery, but a hard prerequisite for Phase 2 —
   not truly optional).** Delivery stays file-based either way; what this item gates is
   *measurement*. It is labelled "optional" only in the sense that the default text path
   runs without it — but **Phase 2 cannot rank any later phase without it**, because
   today claude tasks carry *no* token telemetry at all: `_parse_tokens_used`
   (`ai_agent.py:241`) only matches codex's `tokens used` stderr line, so a claude run
   writes `tokens_used: null` into `meta/usage.json` (see `test_claude_empty_stderr`).
   So treat this as required-before-Phase-2, gated behind a flag only so the *default*
   stays plain text.
   Mechanism: add `--output-format json`, parse the envelope from the captured stdout,
   write `result` back as the plain-text stdout the pipeline expects (keeps every parser
   in `tasks/` untouched), and persist the `usage` splits into `meta/usage.json`.
   **Schema change, not just parsing:** `_save_usage` (`ai_agent.py:256`) currently
   writes only `tokens_used`/`total_tokens`, and `_UsageStats`/`_aggregate_usage` carry
   nothing finer. Persisting input/output/`cache_read_input_tokens` means extending the
   `usage.json` schema *and* `_aggregate_usage`, keeping field names in sync across
   `_save_usage` / `read_agent_usage` / `api_agent.py` — the sync the
   `_aggregate_usage` docstring (`pipeline_setup.py:162-163`) explicitly warns about.
   **Ordering matters — and the restructuring reaches further back than the emptiness
   check.** `run_ai_agent` consumes usage *before* that check: `_parse_tokens_used` reads
   codex's stderr at `ai_agent.py:115` and `_save_usage` writes `usage.json` at
   `ai_agent.py:127`, both ahead of the "exit 0 but stdout empty" check
   (`ai_agent.py:129-141`). With the JSON envelope, usage comes from **stdout**, so the
   whole 115–141 span is restructured: parse the envelope first, rewrite `result` as the
   plain-text stdout, save usage from the envelope, and derive the emptiness signal from
   `result`, not the JSON blob. One more consumer of raw stdout: `_summarise_output`
   (`ai_agent.py:201`) scans it for error patterns ("429", "rate limit") on failures —
   after this change it must scan the extracted `result` text, or news copy that happens
   to mention those words inside the JSON blob yields a false error summary.

4. Prompt-side change: the `_CLI_OUTPUT_INSTRUCTION` block ("Do NOT write any files…")
   stays — with only `Read` available it is largely enforced structurally, but it still
   guides the model away from narrating.

5. Probe the same slimming for the other agents (30-minute experiments each, results go
   into `spec/agents.md`) — **all keep file delivery**:
   - codex: measure baseline `codex exec` overhead via its `tokens used` stderr line; try
     `--skip-git-repo-check` + minimal config (`-c` overrides). codex has no `--tools ""`
     equivalent, so expect a smaller win; **do not** switch to `codex exec -` stdin (it
     hangs on EOF under a non-TTY pipe).
   - antigravity: check `agy --help` for tool/system-prompt controls, but keep `agy -p`
     with file delivery — `agy -p` has silently dropped stdout under a subprocess before.

6. **Pin the CLI and preflight the flags.** The phase rests on `--allowed-tools`,
   `--setting-sources ""`, and `--system-prompt`. These exist in the
   claude CLI verified for this plan (2.1.207), but flag semantics churn between releases
   and an unknown flag makes the CLI exit non-zero — failing *every* task in the run, not
   degrading gracefully. Defenses: pin the CLI version, and add a cheap one-shot preflight
   at pipeline start (run the template against a trivial prompt; if it errors, abort with a
   clear "CLI flags rejected — check version" message instead of failing task-by-task).
7. **Rewrite `spec/agents.md` — it is stale far beyond the template section.** Besides
   `--output-format text` and the wide tool list, it still documents a manifest-native
   contract, a **gemini** backend (not antigravity), a `{prompt}` placeholder (the code
   uses `{prompt_file}`), env vars that no longer exist (`NEWS_RECAP_LLM_GEMINI_*`, the
   model-profile set), and CLI commands gone from `src/` (`llm enqueue-test`,
   `llm worker`). Budget a full rewrite against the current code — backends
   codex/claude/antigravity, the slimmed **file-delivery** template
   (`--allowed-tools "Read"`, stripped system prompt/settings, prompt still read from
   `{prompt_file}`), the real env-var set from `config.py`, the Phase 0 default agent —
   not a one-section touch-up. If item 3 is taken, also document the optional JSON
   envelope.
   **Collision resolution (not just "coordinate"):** both this plan and the sandboxing
   plan edit the *same* `config.py` template and `spec/agents.md`, and the template edit
   is byte-identical between them. So whichever plan lands first owns the change; in the
   other plan that same edit becomes a no-op verified by its template test. Land the
   `config.py`/`agents.md` change once, under whichever plan reaches it first, and drop
   the duplicate rather than re-applying it.
8. Tests: unit test that the rendered claude template carries `{prompt_file}` (file
   delivery) and `--allowed-tools "Read"` only; regression run of one full pipeline on a
   small article set. If item 3 is taken, add an envelope-parsing unit test (fixture
   JSON, including the empty-`result` case).

Side benefit: narrowing `--allowed-tools` to `Read` removes every network/write tool, so
a hijacked claude cannot exfiltrate or modify the host (only read). This *is* Phase 0 of
the sandboxing plan; the two plans share the one template edit.

## Phase 2 — Real telemetry before structural surgery (~0.5 day)

Phase 1 item 3 (JSON telemetry) is a **hard prerequisite** for this phase — enable it
first (it is a no-op for delivery; see item 3). With it, accurate per-call usage becomes
available. Extend the existing
`_log_pipeline_token_summary` (flow.py) to report input/output/cache-read splits per
phase and per launch count, and persist the summary into the digest index entry via
`_aggregate_usage` (pipeline_setup.py) — which item 3 must already have taught to carry
the finer splits (input/output/`cache_read_input_tokens`), not just `total_tokens`. Run
~1 week of daily pipelines. All later phases are ranked by these numbers, not by guesses.
Expected ranking (to be confirmed): launch overhead (fixed by Phase 1) >
oneshot_digest > enrich > classify > dedup > merge/refine.

## Phase 3 — Launch-count audit (~0.5 day, verification only — both proposed wins fell through)

Audit outcome: of the two mechanisms this phase originally proposed, retry-coalescing
turned out to be **already implemented** (item 3) and prompt-prefix caching is
**structurally impossible on the CLI backend** (item 4). What remains here is pinning
the existing behavior with a test; the real launch-count and payload wins live in
Phases 4–5. The batching constraint below still stands and governs those phases too.

> **HARD CONSTRAINT — do NOT enlarge per-prompt batch sizes.** The current batch caps
> (`classify._MAX_BATCH = 300`, `enrich._MAX_BATCH = 20` + `_MAX_BATCH_CHARS = 60_000`)
> are **experimentally-tuned ceilings**, not arbitrary defaults. Past a model's working
> point, packing more headlines/articles into one prompt makes the model **silently drop
> or miscount items** — which is exactly what the `_MIN_RECOGNITION_RATE` guards
> (0.8 classify / 0.50 enrich) were added to catch. Cross that point and the batch fails
> its guard and re-runs *whole*, so "fewer, fatter launches" does not save work — it
> **breaks the pipeline or makes it slower**. Therefore: **the ceilings do not go up in
> this plan.** The legitimate way to cut launch count is to send the model *less*
> (Phase 4 cache; Phase 5 local clustering), not to cram *more* per call. Any change to a
> cap is an opt-in, guard-watched live experiment behind an env override — never a blind
> default bump, and never above the point where recognition starts to slip.

1. ~~classify: raise `_MIN_BATCH` 50 → 300.~~ **Rejected as a default change.** Raising
   `_MIN_BATCH` pushes the *typical* batch size up toward the 300 ceiling
   (e.g. a 350-article day goes from 3×~117 to 2×175), i.e. it enlarges prompts — the very
   thing this phase forbids. The classify guard is strict (`_MIN_RECOGNITION_RATE = 0.8`)
   and the model must print EXACTLY `{expected_count}` lines; one miscount in a larger
   batch fails the whole batch and re-runs it. If a bigger operating point is ever wanted,
   prove it first: sweep batch size on historical days under the live guard
   (`NEWS_RECAP_CLASSIFY_MAX_BATCHES` already exists for this), find the size where
   recognition first drops below 0.8, and set the default *below* it — do not assume the
   coded 300 max is a safe operating point just because it is the hard limit. Default
   stays as tuned; Phase 5 is the real launch-count win for classify.
2. ~~enrich: raise `_MAX_BATCH` 20 → 40.~~ **Rejected.** This directly raises the tuned
   article-count ceiling and is precisely the "more articles per prompt → model stops
   processing them" failure the constraint above describes. `_MAX_BATCH = 20`,
   `_MAX_ARTICLE_CHARS = 5_000`, and `_MAX_BATCH_CHARS = 60_000` stay as tuned. (There is
   also no headroom argument for it: 40 full rewrites risk the
   `CLAUDE_CODE_MAX_OUTPUT_TOKENS = 64000` output cap too.)
3. ~~Retry rounds: coalesce unparsed leftovers into one launch per round.~~ **Already
   implemented — this is the current behavior, not a change.** `_run_enrich` pools the
   leftovers from *all* batches of a round into a single `remaining` list and re-packs it
   greedily through `split_into_enrich_batches`, which only opens a new batch when
   `_MAX_BATCH` / `_MAX_BATCH_CHARS` would be exceeded (`enrich.py:266-300`); there is no
   re-splitting along the original batch boundaries. Remaining work is a **pinning
   test**: assert that leftovers from several batches coalesce into the minimal number of
   cap-respecting batches on the next round, so a refactor cannot silently regress it.
4. ~~Cache-friendly prompt prefixes (move per-batch variables to the end of the
   templates).~~ **Rejected for the CLI backend — structurally impossible, not merely
   low-payoff.** With file delivery the template text never enters the request *prefix*:
   a CLI launch's context is system prompt + tool schemas + the fixed "Read your task
   from {prompt_file}" message, then a `Read` tool_use whose input contains the
   **per-task workdir path** (`ai_agent.py:309` — the path embeds the task id), and only
   then the prompt text as a tool result. The prefix diverges at that tool_use block
   *before* the first template byte, so no reordering inside `prompts.py` can create a
   shared cacheable prefix across batches. Meanwhile the part that *is* shared — system
   prompt + tools + the fixed user message — is already byte-identical across launches
   with no prompt work (that is exactly the caching caveat in the baseline section).
   The idea stays relevant **only for the API backend** (prompts sent directly as
   messages), which this plan keeps experiment-only. If the API path ever becomes real,
   revisit under the original caveats:
   - **1024-token minimum.** Anthropic prompt caching has a minimum cacheable prefix
     (~1024 tokens for Sonnet/Opus). The static part of the classify/enrich templates
     (`prompts.py:42-98`) is only a few hundred tokens unless `{exclude_policy}` /
     `{follow_policy}` is large — below the floor there is nothing to cache.
   - **Parallel batches race the cache write.** Batches of one step launch concurrently
     via the `ThreadPoolExecutor`, so same-prefix requests fire at once and all miss the
     not-yet-written cache; the discount only materializes for *sequential* reuse.

## Phase 4 — Cross-pipeline result cache (~1 day)

`_compute_article_window` anchors each new pipeline to the last completed digest's
cutoff, so day-to-day overlap is small in normal operation. The cache pays off in
the other frequent modes: re-runs after failures, `--from`/`--all` runs, and
experiment iterations over the same window (the checkpoint only helps *within* one
pipeline dir).

1. **Two caches, not one** — verdicts and enriched titles have *different* key inputs,
   and a single combined key over-invalidates (an exclude-policy edit would needlessly
   wipe every enriched title). Next to `ResourceCache`:
   - `{data_dir}/verdicts/` — value `{verdict, created_at}`;
   - `{data_dir}/enriched/` — value `{enriched_title, created_at}`.
   The key inputs live in the **key**, so the filename must encode them:
   `{article_id}-{key_hash}.json`, not bare `{article_id}.json` (a bare id cannot carry
   the key; entries under superseded keys are just unreferenced files the GC collects).
2. classify: before batching, pull cached verdicts; send only cache misses to the
   LLM. enrich: same for `enriched_title`.
3. Invalidation — per-cache key hash over **everything that changes the output**:
   - **verdict key**: exclude-policy text (policy edit → re-classify) + article title
     (feed edit → re-classify) + model (a swap must not serve stale verdicts) + the
     `RECAP_CLASSIFY_BATCH_PROMPT` template body;
   - **enriched-title key**: digest language (titles are language-specific) + article
     title + **the resource text** — the title is rewritten from the fetched article
     body (`_build_enrich_entries` reads it from `ResourceCache`), so a re-fetched or
     updated body must not serve a stale title — + model + the
     `RECAP_ENRICH_BATCH_PROMPT` template body.
   Prefer template-body hashes over a manually-bumped version tag: a manual tag is the
   *same class of footgun* this item otherwise fixes for `model` — easy to forget on a
   prompt edit, silently serving stale results. Hashing the template string makes any
   prompt change invalidate automatically. GC with the same retention as article
   partitions.
4. Expected effect: near-zero cost for repeated experiment runs — which is exactly
   when quota pressure is highest today.

## Phase 5 — Structural: local clustering replaces LLM grouping (~3–5 days, biggest payload cut)

Today `oneshot_digest` sends **every kept headline** to the LLM in 200-article
batches and asks it to invent the grouping; the `merge_sections` step (a sub-step
inside `oneshot_digest`, driven by `RECAP_MERGE_SECTIONS_PROMPT`) and the separate
`refine_layout` phase (`flow.py`) exist solely to repair the artifacts of that batch
split. Embeddings for every article are already computed twice per run (dedup, and
`reorder_articles` inside oneshot ordering) — the grouping signal is already on disk.

New shape:

0. **Go/no-go pre-check before committing the 3–5 days (½ day).** The entire payoff
   rests on the local clustering being *good enough* — but the dedup embeddings
   (e5/sentence-transformers) are tuned for **near-duplicate** detection at a high
   threshold. **Topic** grouping is a looser, different task; at a low threshold these
   embeddings can drift or collapse into one giant catch-all cluster. Before writing the
   new pipeline, run the low-threshold `group_similar` over a few historical days and
   eyeball cluster coherence. If topics don't separate cleanly, stop here — the rest of
   Phase 5 is not worth it, and the A/B week (below) would only discover this after the
   build. One more precondition to check explicitly: `build_embedder`
   (`recap/dedup/embedder.py:96-112`) **silently falls back to `HashingEmbedder`** when
   sentence-transformers cannot load — on the hash embedder both this pre-check and
   production clustering produce garbage behind a green pipeline. Run the pre-check with
   the fallback disabled (`allow_fallback=False`) and assert the real
   `intfloat/multilingual-e5*` model is in use before trusting any clustering result.
1. **Local topic clustering** over the existing embeddings (extend `group_similar` in
   `src/news_recap/recap/dedup/cluster.py` — the *recap* dedup, not the ingestion dedup
   service — with a lower threshold tier, or agglomerative clustering; singletons
   allowed, unlike dedup). Output: topic blocks.
2. **Per-cluster LLM call** (tiny): "here are 3–8 related headlines — write the 1–2
   sentence BLOCK description in {language}". Pack many clusters per launch exactly
   like `RECAP_DEDUP_MULTI_PROMPT` packs clusters today (`CLUSTER N:` framing —
   proven parseable in this codebase).
3. **One small sections call**: input = block descriptions only (not articles);
   output = section labels + block assignment + section summaries. Input size is
   O(blocks) ≈ 30–60 lines instead of O(articles).
4. Delete the `merge_sections` sub-step and the `refine_layout` phase (their job no
   longer exists), plus the coverage-repair machinery driven by batch splits.
   Keep-separate topics (`follow_policy`) move into the sections call. **This is more
   than a code deletion — it edits the pipeline's phase graph**, so budget for the whole
   surface: the `--stop-after` phase list (`main.py:240`, `docs/src/{en,ru}/cli.md`), the
   `completed_phases` schema in `digest.json` (`test_pipeline_setup.py`), the
   oneshot resume path (`oneshot_digest.py:310`, where `reorder_articles` yields a
   different order on resume), and the `refine_layout`/`merge_sections` tests
   (`test_refine_layout.py`, `test_fuzzy_merge.py`). The ~3–5 day estimate is on the
   light side once these are counted; treat it as build-only, exclusive of the A/B week.
5. **Quality guardrail — hybrid review pass** (cheap, optional flag): the LLM sees
   only the final block descriptions and may propose merges of semantically
   duplicate blocks — mirrors `_fuzzy_merge_blocks` which already exists.

Token effect: the model never reads the full article list; per-run digest-phase
input drops from `O(articles × (1 + merge + refine))` to
`O(articles-in-clusters for naming) + O(blocks)` — roughly 3–5× less on the digest
phases, and eliminates the two repair launches entirely.

Quality validation before switching the default:

- Run both pipelines on the same `pipeline_input` for ~1 week
  (`NEWS_RECAP_STOP_AFTER` + a `--experimental-grouping` flag).
- Compare: coverage (metric already exists), block count distribution,
  keep-separate-topic compliance (scriptable), and a manual read of the rendered
  digests side by side (the web viewer can serve both pipeline dirs).

## Phase 6 — Optional: local classify cascade (experiment)

classify is the only phase that LLM-touches *all* articles daily. The exclude
policy is a set of topic descriptions; e5 embeddings can score
headline↔policy-topic similarity locally. Cascade: confident ok/exclude decided
locally, only the uncertain middle band (expect 20–40% of the stream) goes to the
LLM. Training/calibration data is already accumulating for free: every past
digest.json holds LLM verdicts.

Run in **shadow mode** first: local scorer logs its verdict next to the LLM's;
enable the filter only for bands where agreement exceeds 95%. The `vague` class is
likely too subtle for embeddings alone — keep it LLM-side; the win is the bulk
ok/exclude triage.

## Expected impact summary

| Phase | Effort | Token effect | Quality risk |
|---|---|---|---|
| 0. agy as code default | 0.5 d | none directly — grounds the ranking: makes the free, request-capped backend the one the defaults actually exercise | none (env opt-out unchanged for codex/claude users) |
| 1. Slim claude (file delivery) | 1–2 d | strips system prompt/settings + all tools but `Read`; saving smaller than the rejected tool-less path, and **currently unmeasured** — re-measure first (Phase 1 item 1) as a go/no-go | none (keeps file delivery) |
| 2. Telemetry | 0.5 d | enables measurement; **hard prerequisite** for ranking phases 4–6 | none |
| 3. Launch-count audit | 0.5 d | ~0 new savings — retry-coalescing already implemented (pin with a test); prefix caching rejected for CLI (file delivery keeps template text out of the request prefix), API-only if ever | none |
| 4. Cross-pipeline cache | 1 d | −~100% on re-runs/experiments | none |
| 5. Local clustering digest | 3–5 d | ~3–5× on digest phases; kills 2 phases | medium — gated by A/B week |
| 6. Classify cascade | experiment | −20–40% of classify | medium — gated by shadow mode |

Recommended order: 0 → 1 → 2 → 4 → 5 → 6, with Phase 3's pinning test folded into
Phase 2's telemetry week — **conditional on Phase 1 item 1's
measurement.** If the slimmed launch turns out only modestly cheaper than 24 k, demote
Phase 1 and pull Phases 4–5 forward, since the win then lives in fewer launches and
smaller payloads rather than per-launch overhead. Phases 0–4 change no pipeline
semantics; Phase 5 is the only structural change and is gated by both a clustering
go/no-go pre-check (Phase 5 item 0) and a side-by-side quality week. Backend note — **all
backends benefit; none is cost-free.** On the opt-in claude/codex tiers the win is token
quota (Phase 1 overhead + Phases 4–5 payload). On the agy default (Phase 0) the binding
constraint is its per-day/per-week **request cap**, so Phases 4–5 (fewer launches, smaller
payloads) are the most valuable there — and where agy's budget is also token-metered,
slimming its launch (Phase 1 item 5) helps too. Because a single run fires 10–40 launches
against a free allowance that has been as low as ~20/day, cutting launch count on agy is
closer to *existential* than to *nice-to-have*: it is the difference between the pipeline
running daily and the account being locked out.

## Sources (agy free-tier limits)

Antigravity free-tier quotas are request- and token-capped with day/week lockouts, and the
free allowance has been cut sharply since launch (≈250 → ≈20/day on Gemini Flash). Verify
current numbers before tuning, they move:

- Google Antigravity — changes to plans / rate limits: <https://antigravity.google/blog/changes-to-antigravity-plans>
- Google blog — higher rate limits for Pro/Ultra (implies the free-tier floor):
  <https://blog.google/feed/new-antigravity-rate-limits-pro-ultra-subsribers/>
- Antigravity usage & rate limits overview (2026): <https://antigravity.im/limits>
- Gemini API rate limits (RPD/TPM reset semantics): <https://ai.google.dev/gemini-api/docs/rate-limits>
