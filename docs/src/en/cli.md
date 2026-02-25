# CLI

`news-recap` is operated from CLI commands grouped by workflow stage.

## Command Map

- `ingest`: source import, stats, dedup inspection.
- `recap`: daily digest pipeline (classify, enrich, group, synthesize, compose).

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

The pipeline goes through six stages: classify → enrich → group →
deep-enrich → synthesize → compose. Each stage is checkpointed, so
a resumed run skips already-completed stages.

```bash
news-recap recap run
news-recap recap run --date 2026-02-18
news-recap recap run --agent claude --stop-after classify
news-recap recap run --limit 50
```

Key options:
- `--data-dir`
- `--date` (business date, defaults to today UTC)
- `--agent` (`codex`, `claude`, or `gemini`)
- `--limit` (cap number of articles loaded)
- `--stop-after` (`classify`, `enrich`, `group`, `enrich_full`, `synthesize`, `compose`)

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

> **Subscription vs API billing.** CLI agents (`claude`, `codex`, `gemini`) check
> for vendor API keys first. If a key is set, usage is billed to your API account
> (pay-per-token). To use your subscription's included quota instead, unset the key:
>
> ```bash
> unset ANTHROPIC_API_KEY   # Claude — use Claude Pro/Max subscription
> unset OPENAI_API_KEY      # Codex — use ChatGPT/Codex subscription
> unset GEMINI_API_KEY      # Gemini — use Google AI subscription
> ```

- `NEWS_RECAP_LLM_DEFAULT_AGENT` — default agent (`codex`, `claude`, or `gemini`).
- `NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP` — per-task-type model profile (`fast`/`quality`).
- `NEWS_RECAP_CODEX_COMMAND_TEMPLATE` — command template for Codex agent.
- `NEWS_RECAP_CLAUDE_COMMAND_TEMPLATE` — command template for Claude agent.
- `NEWS_RECAP_GEMINI_COMMAND_TEMPLATE` — command template for Gemini agent.
- `NEWS_RECAP_LLM_CODEX_MODEL_FAST` / `NEWS_RECAP_LLM_CODEX_MODEL_QUALITY`
- `NEWS_RECAP_LLM_CLAUDE_MODEL_FAST` / `NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY`
- `NEWS_RECAP_LLM_GEMINI_MODEL_FAST` / `NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY`

### Prefect
- `NEWS_RECAP_PREFECT_MODE` — `ephemeral` (default), `server`, or `auto`.
- `PREFECT_API_URL` — Prefect server URL (required when mode is `server`).

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap recap --help
```
