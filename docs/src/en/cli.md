# CLI

`news-recap` is operated from CLI commands grouped by workflow stage.

## Command Map

- `ingest`: source import, stats, dedup inspection.
- `recap`: daily digest pipeline (classify, enrich, deduplicate, map, reduce, split, group_sections, summarize).

## Common Notes

- Most commands support `--data-dir` to point to a specific data directory.
- Data is stored as JSON files with daily partitioning; old partitions are
  garbage-collected automatically based on `NEWS_RECAP_GC_RETENTION_DAYS`.

## Ingestion Commands

### `ingest daily`
Run one ingestion cycle from RSS/Atom feeds.

```bash
news-recap ingest daily
news-recap ingest daily --feed-url https://example.com/feed.xml
```

Key options:
- `--feed-url` (repeatable)
- `--data-dir`

If `--feed-url` is omitted, feeds are loaded from:
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_FEED_URL`

### `ingest stats`
Show ingestion and dedup metrics in a rolling window.

```bash
news-recap ingest stats --hours 24 --recent-runs 5
```

Key options:
- `--hours`
- `--source`
- `--recent-runs`

### `ingest clusters`
Inspect dedup cluster distribution for a run.

```bash
news-recap ingest clusters --hours 24 --limit 20
news-recap ingest clusters --run-id <run_id> --show-members
```

Key options:
- `--run-id` or `--hours`/`--source` for run resolution
- `--min-size`
- `--members-per-cluster`
- `--show-members`

### `ingest duplicates`
Print duplicate cluster examples (cluster size >= 2).

```bash
news-recap ingest duplicates --hours 24 --limit-clusters 10
```

Key options:
- `--run-id` or `--hours`/`--source`
- `--limit-clusters`
- `--members-per-cluster`

## Recap Pipeline Commands

### `recap run`
Run the full news digest pipeline for a business date.

The pipeline goes through nine stages: classify → load_resources → enrich →
deduplicate → map_blocks → reduce_blocks → split_blocks → group_sections →
summarize. Each stage is checkpointed, so a resumed run skips
already-completed stages.

```bash
news-recap recap run
news-recap recap run --api
news-recap recap run --date 2026-02-18
news-recap recap run --agent claude --stop-after classify
news-recap recap run --limit 50
```

Key options:
- `--data-dir`
- `--date` (business date, defaults to today UTC)
- `--agent` (`codex`, `claude`, or `gemini`)
- `--limit` (cap number of articles loaded)
- `--api` (use direct Anthropic API instead of CLI agents)
- `--fresh` (discard any incomplete pipeline and start a new one)
- `--oneshot` (replace the map→reduce→split→group→summarize stages with parallel
  batches of ~200 articles, then merge sections via a single follow-up LLM call)
- `--use-api-key` (keep vendor API keys in the agent subprocess environment;
  by default they are removed so the agent uses its subscription quota)
- `--stop-after` (`classify`, `load_resources`, `enrich`, `deduplicate`, `map_blocks`, `reduce_blocks`, `split_blocks`, `group_sections`, `summarize`)

## API Mode

By default the recap pipeline runs LLM tasks by spawning CLI agent subprocesses
(`codex`, `claude`, `gemini`). **API mode** replaces subprocess calls with direct
Anthropic SDK calls — no CLI agents required.

> API mode v1 supports Anthropic only. Codex and Gemini are CLI-only for now.

### Quickstart

```bash
export ANTHROPIC_API_KEY=sk-ant-...
news-recap recap run --api
```

`--api` sets `backend=api` and `agent=claude` automatically. No other env vars needed.

### Per-task model map

By default fast tasks use `claude-haiku-4-5-20251001` and the reduce task uses
`claude-sonnet-4-6`. Override individual tasks with `NEWS_RECAP_API_MODEL_MAP`
(comma-separated `task_type=model_id` pairs):

```bash
export NEWS_RECAP_API_MODEL_MAP="recap_reduce=claude-sonnet-4-6,recap_summarize=claude-sonnet-4-6"
```

### API mode environment variables

- `NEWS_RECAP_EXECUTION_BACKEND` — `cli` (default) or `api`.
- `NEWS_RECAP_API_MODEL_MAP` — per-task model overrides (`task_type=model_id,...`).
- `NEWS_RECAP_API_MAX_PARALLEL` — initial concurrency cap (default `5`). Automatically
  downshifted on rate-limit errors and recovered after consecutive successes.
- `NEWS_RECAP_API_TIMEOUT_SECONDS` — per-call timeout (default `120`).
- `NEWS_RECAP_API_CONCURRENCY_RECOVERY_SUCCESSES` — consecutive successes needed
  to increment the concurrency cap by 1 after a downshift (default `10`).
- `NEWS_RECAP_API_RETRY_MAX_BACKOFF_SECONDS` — exponential backoff ceiling (default `60`).
- `NEWS_RECAP_API_RETRY_JITTER_SECONDS` — uniform jitter added to each backoff (default `5`).
- `NEWS_RECAP_API_DOWNSHIFT_PAUSE_SECONDS` — extra pause after a rate-limit downshift
  before the next slot acquire (default `2`).

## Important Environment Variables

### Data and Storage
- `NEWS_RECAP_DATA_DIR` — root directory for all data files.
- `NEWS_RECAP_GC_RETENTION_DAYS` — how many days of article partitions to keep (default 7).
- `NEWS_RECAP_DIGEST_LOOKBACK_DAYS` — how many days of articles to include in a digest (default 3).

### RSS Feeds
- `NEWS_RECAP_RSS_FEED_URLS` — comma-separated list of feed URLs.
- `NEWS_RECAP_RSS_FEED_URL` — single feed URL (convenience alias).
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED` — max items to fetch per feed.
- `NEWS_RECAP_RSS_FEED_ITEMS` — per-feed item overrides (`<feed_url>|<items>,...`).

### LLM Agents

> **Subscription vs API billing.** When spawning CLI agents (`claude`, `codex`, `gemini`)
> as subprocesses, `recap run` removes vendor API keys
> (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`)
> from the subprocess environment by default — so the agent uses its subscription
> quota rather than billing your API account per token.
>
> In `--api` mode the Anthropic SDK needs the key and it is **never removed**.
> The `--use-api-key` flag has no effect in `--api` mode.
>
> To explicitly pass the API key to a CLI agent (pay-per-token billing), use `--use-api-key`:
>
> ```bash
> news-recap recap run --use-api-key
> ```

- `NEWS_RECAP_LLM_DEFAULT_AGENT` — default agent (`codex`, `claude`, or `gemini`).
- `NEWS_RECAP_LLM_TASK_MODEL_MAP` — per-task-type model overrides by agent
  (`task_type:agent=model_flags,...`).
- `NEWS_RECAP_CODEX_COMMAND_TEMPLATE` — command template for Codex agent.
- `NEWS_RECAP_CLAUDE_COMMAND_TEMPLATE` — command template for Claude agent.
- `NEWS_RECAP_GEMINI_COMMAND_TEMPLATE` — command template for Gemini agent.

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap recap --help
```
