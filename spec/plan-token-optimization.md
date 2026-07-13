# Plan: Token Usage Reduction (CLI Backend)

Status: proposed. Companion plan: `plan-agent-sandboxing.md` (its Phase 0 overlaps
with Phase 1 here — the thin-client claude template serves both goals).

Billing model: subscription (CLI agents), so "cost" = subscription **quota**
consumption, measured in tokens with provider-side cache discounts. The API backend
stays experiment-only. Goal: cut token consumption substantially without a
measurable quality drop.

## Measured baseline (research done 2026-07-13, claude CLI, live calls)

| Launch mode | Input tokens for a 10-token prompt |
|---|---|
| Default `claude -p` | **24 378** (24 368 system prompt + tool schemas, cached-write) |
| `claude -p --tools "" --system-prompt "…" --setting-sources ""`, prompt on stdin | **167** |

Two further verified facts:

- A classify-style task (numbered headlines → verdict per line) works correctly in
  the stripped mode with stdin delivery — no `Read` tool needed.
- `--output-format json` returns a single-object envelope with
  `result` (the text) and `usage` (`input_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `output_tokens`) plus `modelUsage` and
  `total_cost_usd` — full per-call telemetry that text mode does not provide.
- Caveat: `--bare` mode must NOT be used — it restricts auth to `ANTHROPIC_API_KEY`
  (OAuth subscription auth is never read), which defeats the subscription model.

Implication: with the current pipeline shape (typically 10–40 CLI launches per run:
classify batches + enrich batches × up to 3 retry rounds + dedup batches +
oneshot batches + merge + refine), **launch overhead alone is ~0.25–1.0 M input
tokens per day** — very likely the single largest line item, ahead of any payload.

## Phase 1 — Thin-client claude launches (~1–2 days, ~99% overhead cut per launch)

Turn the claude CLI into a near-zero-overhead API client that bills to the
subscription.

1. New default claude template (config.py):

   ```
   claude -p {model} --output-format json --no-session-persistence \
     --setting-sources "" --tools "" \
     --system-prompt "You are a text-processing engine. Follow the task instructions exactly. Reply with plain text only."
   ```

   Prompt delivered on **stdin** instead of `"Read your task from {prompt_file}"`.

2. `run_subprocess` gains an optional `stdin_path: Path | None` (currently hardcoded
   `stdin=subprocess.DEVNULL`); `_run_agent_cli` passes the prompt file when the
   template is marked stdin-mode. Template marking: a new `{prompt_stdin}` pseudo-
   placeholder, or simplest — a per-agent `prompt_delivery: "stdin" | "file"` field
   in `RoutingDefaults` (schema_version bump).

3. JSON envelope handling in `ai_agent.py`: when the template requested JSON output,
   parse the envelope from the captured stdout file, write `result` back as the
   plain-text stdout the rest of the pipeline expects (keeps every parser in
   `tasks/` untouched), and persist `usage` into `meta/usage.json` (real
   input/output/cache splits instead of the current codex-only stderr regex).
   Malformed envelope → treat as agent failure with the raw tail logged (existing
   `_log_agent_output` path).
   **Ordering matters:** `run_ai_agent` checks "exit 0 but stdout empty"
   (`ai_agent.py:129-141`) against the *raw* stdout. The envelope must be parsed and
   `result` written back **before** that check — otherwise a valid JSON envelope
   (non-empty stdout) whose `result` is empty passes the check wrongly, and any
   parse/rewrite must set the emptiness signal from `result`, not from the JSON
   blob. Do the parse right after `run_subprocess` returns and before the
   `stdout_empty` test.

4. Prompt-side change: the `_CLI_OUTPUT_INSTRUCTION` block ("Do NOT write any
   files…") stays — it is now enforced structurally (no tools) but still guides the
   model away from narrating.

5. Probe the same trick for the other agents (30-minute experiments each, results
   go into `spec/agents.md`):
   - codex: measure baseline `codex exec` overhead via its `tokens used` stderr
     line; try `--skip-git-repo-check` + minimal config (`-c` overrides) — codex has
     no known `--tools ""` equivalent, so expect a smaller win; stdin delivery via
     `codex exec -` if supported.
   - antigravity: check `agy --help` for tool/system-prompt controls.

6. **Pin the CLI and preflight the flags.** The whole phase rests on
   `--tools ""`, `--no-session-persistence`, `--setting-sources ""`, and
   `--output-format json`. These exist in the claude CLI verified for this plan
   (2.1.207), but flag semantics churn between releases and an unknown flag makes the
   CLI exit non-zero — failing *every* task in the run, not degrading gracefully.
   Defenses: pin the CLI version (free once the sandbox image from the companion plan
   ships — bake the exact version into the Dockerfile), and add a cheap one-shot
   preflight at pipeline start (run the template against a trivial prompt; if it
   errors, abort with a clear "CLI flags rejected — check version" message instead of
   failing task-by-task).
7. **Update `spec/agents.md`.** It currently documents `--output-format text` and
   warns that "JSON mode can include usage metadata that breaks the stdout recovery
   path" (`agents.md:104`) — this phase deliberately switches to JSON and solves that
   by rewriting stdout to `result` (item 3). Bring the spec in line: document the
   thin-client template, the JSON envelope, and stdin delivery. (The sandboxing plan
   also touches `agents.md`; coordinate so one edit doesn't clobber the other.)
8. Tests: unit test for envelope parsing (fixture JSON, including the empty-`result`
   case from item 3), stdin plumbing test with the echo mock agent, regression run of
   one full pipeline on a small article set.

Side benefit: with `--tools ""` the claude agent physically cannot touch files or
network — this is Phase 0 of the sandboxing plan for free.

## Phase 2 — Real telemetry before structural surgery (~0.5 day)

Phase 1 makes accurate per-call usage available. Extend the existing
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
| 1. Thin-client claude | 1–2 d | −24 k/launch → often −50–80% of total | none (verified) |
| 2. Telemetry | 0.5 d | enables measurement | none |
| 3. Batching + cache-friendly prefixes | 1 d | fewer launches; cache-read discount on repeats | low |
| 4. Cross-pipeline cache | 1 d | −~100% on re-runs/experiments | none |
| 5. Local clustering digest | 3–5 d | ~3–5× on digest phases; kills 2 phases | medium — gated by A/B week |
| 6. Classify cascade | experiment | −20–40% of classify | medium — gated by shadow mode |

Recommended order: 1 → 2 → 3+4 (parallel) → 5 → 6. Phases 1–4 change no pipeline
semantics; Phase 5 is the only structural change and is gated by a side-by-side
quality week.
