# Plan: Token Usage Reduction (CLI Backend)

Status: proposed. Companion plan: `plan-agent-sandboxing.md` (its Phase 0 overlaps
with Phase 1 here — the slimmed claude template serves both goals; see that plan's
*Backend priority* for which backend is the default). **Both plans retain
file-based prompt delivery — stdin proved unstable (see the Phase 1 finding); the claude
launch is slimmed while it keeps its `Read` tool to read `{prompt_file}`, and results are
still captured from stdout.**

Billing model: the pipeline's **default backend is antigravity (`agy`), which runs free
with no subscription** (per the companion plan's backend priority) — its "cost" is
free-tier rate/capacity limits (RPM), not token spend. **claude** and **codex** are
optional quality-tier backends; on those, "cost" = subscription **quota** consumption,
measured in tokens with provider-side cache discounts. The API backend stays
experiment-only. This plan's launch-overhead cut (Phase 1) targets the claude tier; the
launch-count and caching work (Phases 3–4) also relieve the free agy default by cutting
calls/retries against its rate limits. Goal: cut token consumption substantially without
a measurable quality drop.

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
any payload. On the free agy default there is no token bill; the equivalent pressure is
call count against its free-tier RPM, which Phases 3–4 address.

## Phase 1 — Slim claude launches, file delivery kept (~1–2 days)

Cut the ~24 k-token launch overhead as far as possible **without** giving up the
working file-based prompt delivery. The tool-less + stdin path (measured at 167 tokens)
is **rejected**: stdin is unreliable at our sizes (see the finding above). We keep
`{prompt_file}` and narrow everything else.

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
     real saving (expected: far below 24 k, above the tool-less 167).

2. Result retrieval is **unchanged**: the agent writes to stdout, the parent captures
   `output/agent_stdout.log`, and every parser in `tasks/` reads it via
   `read_agent_stdout`. No `--output-format json` rewrite is required for the default
   path.

3. **Optional telemetry (decoupled, off by default):** if per-call usage splits are
   wanted for Phase 2, add `--output-format json`, parse the envelope from the captured
   stdout, write `result` back as the plain-text stdout the pipeline expects (keeps every
   parser in `tasks/` untouched), and persist `usage` into `meta/usage.json`.
   **Ordering matters:** `run_ai_agent` checks "exit 0 but stdout empty"
   (`ai_agent.py:129-141`) against the *raw* stdout, so parse and rewrite `result`
   **before** that check and derive the emptiness signal from `result`, not the JSON blob.
   Gate this behind a flag so the default stays plain text and delivery is untouched.

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
7. **Update `spec/agents.md`.** It currently documents `--output-format text` and a wide
   tool list; bring it in line with the slimmed **file-delivery** template
   (`--allowed-tools "Read"`, stripped system prompt/settings, prompt still read from
   `{prompt_file}`). If item 3 is taken, also document the optional JSON envelope. (The
   sandboxing plan also touches `agents.md`; coordinate so one edit doesn't clobber the
   other.)
8. Tests: unit test that the rendered claude template carries `{prompt_file}` (file
   delivery) and `--allowed-tools "Read"` only; regression run of one full pipeline on a
   small article set. If item 3 is taken, add an envelope-parsing unit test (fixture
   JSON, including the empty-`result` case).

Side benefit: narrowing `--allowed-tools` to `Read` removes every network/write tool, so
a hijacked claude cannot exfiltrate or modify the host (only read). This *is* Phase 0 of
the sandboxing plan; the two plans share the one template edit.

## Phase 2 — Real telemetry before structural surgery (~0.5 day)

With Phase 1 item 3 (optional JSON telemetry) enabled, accurate per-call usage becomes
available. Extend the existing
`_log_pipeline_token_summary` (flow.py) to report input/output/cache-read splits per
phase and per launch count, and persist the summary into the digest index entry
(`_aggregate_usage` already exists in pipeline_setup.py). Run ~1 week of daily
pipelines. All later phases are ranked by these numbers, not by guesses.
Expected ranking (to be confirmed): launch overhead (fixed by Phase 1) >
oneshot_digest > enrich > classify > dedup > merge/refine.

## Phase 3 — Fewer, fatter launches + cache-friendly prompts (~1 day)

Even at 167 tokens/launch, fewer calls mean less latency and fewer retry rounds; for
codex/antigravity (overhead not eliminated) this is the main lever.

1. classify: raise `_MIN_BATCH` 50 → 300 (`classify.py`). The model already handles
   `_MAX_BATCH = 300` headlines; today a 350-article day produces 2–7 launches where
   1–2 suffice.
2. enrich: raise `_MAX_BATCH` 20 → 40 and keep `_MAX_BATCH_CHARS = 60_000` as the
   real limiter. The `===ARTICLE===` separator parsing is count-agnostic; verify the
   recognition-rate guard (`_MIN_RECOGNITION_RATE = 0.50`) still holds on a live
   batch before flipping.
3. Retry rounds (enrich `_run_enrich`, up to 3 rounds): retry only the *unparsed*
   articles (already the case) but batch them into a single launch per round rather
   than re-splitting.
4. Provider-side prompt caching (subscription quota counts cache reads at a steep
   discount): make every batch of the same step share a byte-identical prompt
   *prefix*. Concretely: in `prompts.py` move all per-batch variables
   (`expected_count`, `article_count`, `total`) from the middle of the templates to
   the end, after the static instructions. **Gate this on Phase 2 telemetry — do not
   reorder prompts blind.** Two things limit the payoff and must be checked first:
   - **1024-token minimum.** Anthropic prompt caching has a minimum cacheable prefix
     (~1024 tokens for Sonnet/Opus). The static part of the classify/enrich templates
     (`prompts.py:42-98`) is only a few hundred tokens unless `{exclude_policy}` /
     `{follow_policy}` is large — below the floor there is simply nothing to cache, so
     the reorder buys nothing. Confirm the static prefix clears 1024 tokens before
     investing.
   - **Parallel batches race the cache write.** Batches of one step launch
     concurrently via the `ThreadPoolExecutor`, so same-prefix requests fire at once
     and all miss the not-yet-written cache. The discount only materializes for
     *sequential* reuse (retries, back-to-back runs, or deliberately launching the
     first batch alone to warm the cache before the rest). Decide whether that
     sequencing is worth it using `cache_read_input_tokens` from Phase 1 telemetry.

## Phase 4 — Cross-pipeline result cache (~1 day)

`_compute_article_window` anchors each new pipeline to the last completed digest's
cutoff, so day-to-day overlap is small in normal operation. The cache pays off in
the other frequent modes: re-runs after failures, `--from`/`--all` runs, and
experiment iterations over the same window (the checkpoint only helps *within* one
pipeline dir).

1. New `VerdictCache` next to `ResourceCache` (`{data_dir}/verdicts/`, one JSON per
   `article_id`): `{verdict, enriched_title, model, created_at}`.
2. classify: before batching, pull cached verdicts; send only cache misses to the
   LLM. enrich: same for `enriched_title`.
3. Invalidation: the cache key must include **everything that changes the verdict** —
   a hash of the exclude-policy text (policy edit → re-classify), the article title
   (feed edit → re-classify), **the model** (`model` is stored in the value but
   nothing invalidates on it — a model swap would otherwise serve stale verdicts),
   **the digest language** (enriched titles are language-specific), and **a
   prompt-template version tag** (bump it whenever the classify/enrich prompt changes
   so old verdicts don't leak across a prompt edit). GC with the same retention as
   article partitions.
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

1. **Local topic clustering** over the existing embeddings (extend
   `dedup/cluster.py:group_similar` with a lower threshold tier, or agglomerative
   clustering; singletons allowed, unlike dedup). Output: topic blocks.
2. **Per-cluster LLM call** (tiny): "here are 3–8 related headlines — write the 1–2
   sentence BLOCK description in {language}". Pack many clusters per launch exactly
   like `RECAP_DEDUP_MULTI_PROMPT` packs clusters today (`CLUSTER N:` framing —
   proven parseable in this codebase).
3. **One small sections call**: input = block descriptions only (not articles);
   output = section labels + block assignment + section summaries. Input size is
   O(blocks) ≈ 30–60 lines instead of O(articles).
4. Delete the `merge_sections` sub-step and the `refine_layout` phase (their job no
   longer exists), plus the coverage-repair machinery driven by batch splits.
   Keep-separate topics (`follow_policy`) move into the sections call.
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
| 1. Slim claude (file delivery) | 1–2 d | strips system prompt/settings + all tools but `Read`; saving smaller than the rejected tool-less path, re-measure | none (keeps file delivery) |
| 2. Telemetry | 0.5 d | enables measurement | none |
| 3. Batching + cache-friendly prefixes | 1 d | fewer launches; cache-read discount on repeats | low |
| 4. Cross-pipeline cache | 1 d | −~100% on re-runs/experiments | none |
| 5. Local clustering digest | 3–5 d | ~3–5× on digest phases; kills 2 phases | medium — gated by A/B week |
| 6. Classify cascade | experiment | −20–40% of classify | medium — gated by shadow mode |

Recommended order: 1 → 2 → 3+4 (parallel) → 5 → 6. Phases 1–4 change no pipeline
semantics; Phase 5 is the only structural change and is gated by a side-by-side
quality week. Backend note: Phase 1 pays off only on the opt-in claude tier; for the free
agy default (the standard backend per the sandboxing plan) the wins are Phases 3–4 (fewer
launches/retries against agy's free-tier RPM) and Phases 5–6 (smaller payloads).
