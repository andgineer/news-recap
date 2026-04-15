# CLI

`news-recap` is operated from CLI commands grouped by workflow stage.

## Command Map

- `ingest`: run one ingestion cycle from RSS/Atom feeds.
- `create`: create a news digest from recent articles.
- `prompt`: export a ready-to-paste LLM prompt from recent articles.
- `info`: show important app paths.
- `list`: show completed digests and uncovered article periods.
- `delete`: delete a digest so its articles become available for the next one.
- `serve`: start the digest web viewer.
- `configure`: view and edit persistent user preferences.
- `schedule set`: install or update the daily scheduled digest job.
- `schedule get`: show current schedule configuration.
- `schedule delete`: remove the daily scheduled digest job.

## Common Notes

- Set the data directory via `NEWS_RECAP_DATA_DIR` (default `~/.news_recap_data`).
- Data is stored as JSON files with daily partitioning; old partitions are
  garbage-collected automatically based on `NEWS_RECAP_GC_RETENTION_DAYS`.

## Ingestion

### `ingest`
Run one ingestion cycle from RSS/Atom feeds.

```bash
news-recap ingest
news-recap ingest --rss https://example.com/feed.xml
```

Key options:
- `--rss` (repeatable)

If `--rss` is omitted, feeds are loaded from:
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_FEED_URL`

## Digest Pipeline Commands

### `create`
Create a news digest from recent articles.

The pipeline goes through the following stages: classify → load_resources → enrich → deduplicate → oneshot_digest (parallel batches + deterministic block dedup + section merge) → refine_layout (optional section consolidation).

Each stage is checkpointed, so a resumed run skips already-completed stages.

```bash
news-recap create
news-recap create --api
news-recap create --agent claude --stop-after classify
news-recap create --limit 50
news-recap create --from-digest 3
```

Key options:
- `--agent` (`codex`, `claude`, or `gemini`)
- `--limit` (cap number of articles loaded)
- `--max-days` (max days to look back for articles; default 2,
  env `NEWS_RECAP_DIGEST_LOOKBACK_DAYS`)
- `--all` (ignore previous digests; include all articles within
  the lookback window)
- `--api` (use direct Anthropic API instead of CLI agents)
- `--fresh` (discard any incomplete pipeline and start a new one)
- `--from-digest N` (reuse articles from an existing digest by ID, as shown by
  `news-recap list`; the business date is taken from the source digest)
- `--use-api-key` (keep vendor API keys in the agent subprocess environment;
  by default they are removed so the agent uses its subscription quota)
- `--stop-after` (`classify`, `load_resources`, `enrich`, `deduplicate`, `oneshot_digest`, `refine_layout`)

### `info`
Show important app paths such as the data directory, workdir, schedule metadata,
and logs.

```bash
news-recap info
```

### `list`
Show completed digests with article counts, date-time coverage, and uncovered
periods (gaps between consecutive digests).

```bash
news-recap list
```

Output is a table (newest first) with columns: numeric ID (`#1` = newest),
business date, article count, article time period, pipeline start time,
elapsed time, total prompt size, total output size, and tokens (when
available). Use the ID with `news-recap serve N` or `news-recap delete N`.

If there are time gaps between consecutive digests' article ranges, they are
shown under "Uncovered periods".

Old pipeline directories are automatically garbage-collected (same retention
as articles, controlled by `NEWS_RECAP_GC_RETENTION_DAYS`).

### `delete`
Delete a completed digest so its articles become available for the next one.

```bash
news-recap delete 1
```

Arguments:
- `DIGEST_ID` — digest ID to delete (as shown by `news-recap list`).

### `serve`
Start the digest web viewer for a specific digest.

```bash
news-recap serve
news-recap serve 2
```

Arguments:
- `DIGEST_ID` (optional) — digest ID to serve (1 = latest, as shown by
  `news-recap list`). Defaults to the latest completed digest.

Key options:
- `--host` — host to bind to (default `127.0.0.1`).
- `--port` — port to bind to (default `8080`).

### `configure`
View and edit persistent user preferences: language, exclude topics, follow
topics, and default LLM agent.

Preferences are stored in `config.json` inside the data directory
(shown by `news-recap info`). They serve as defaults for `create` and `prompt`
commands — CLI flags still override them.

```bash
news-recap configure
```

The command shows current values (with a `(default)` tag for fields that haven't
been set yet), then lets you pick which ones to update:

```
Current settings:
  1. Language:      ru (default)
  2. Exclude:       horoscopes, medical advice, sports (except Russia), ... (default)
  3. Follow:        Russia, Serbia, war in Ukraine (default)
  4. Default Agent: codex (default)

Select fields to update (comma-separated numbers, 'all', or Enter to skip):
```

Priority order (highest wins):

1. CLI flags (`--language`, `--agent`)
2. Config file (`config.json`)
3. Code defaults

## API Mode

By default the digest pipeline runs LLM tasks by spawning CLI agent subprocesses
(`codex`, `claude`, `gemini`). **API mode** replaces subprocess calls with direct
Anthropic SDK calls — no CLI agents required.

> API mode v1 supports Anthropic only. Codex and Gemini are CLI-only for now.

### Quickstart

```bash
export ANTHROPIC_API_KEY=sk-ant-...
news-recap create --api
```

`--api` sets `backend=api` and `agent=claude` automatically. No other env vars needed.

### Per-task model map

By default all tasks use `claude-haiku-4-5-20251001`. Override individual tasks
with `NEWS_RECAP_API_MODEL_MAP` (comma-separated `task_type=model_id` pairs):

```bash
export NEWS_RECAP_API_MODEL_MAP="recap_oneshot_digest=claude-sonnet-4-6,recap_classify=claude-haiku-4-5-20251001"
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

## Scheduled Runs

See [Scheduled Runs](automation.md) for setup, platform details, logs, and troubleshooting.

## Important Environment Variables

### Data and Storage
- `NEWS_RECAP_DATA_DIR` — root directory for all data files (default `~/.news_recap_data`).
- `NEWS_RECAP_GC_RETENTION_DAYS` — how many days of article partitions to keep (default 7).
- `NEWS_RECAP_DIGEST_LOOKBACK_DAYS` — max days of articles to include in a digest (default 2).
  By default the window starts from the last successful digest date; use
  `--all` to always use the full window.

### RSS Feeds
- `NEWS_RECAP_RSS_FEED_URLS` — comma-separated list of feed URLs.
- `NEWS_RECAP_RSS_FEED_URL` — single feed URL (convenience alias).
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED` — max items to fetch per feed.
- `NEWS_RECAP_RSS_FEED_ITEMS` — per-feed item overrides (`<feed_url>|<items>,...`).

### LLM Agents

> **Subscription vs API billing.** When spawning CLI agents (`claude`, `codex`, `gemini`)
> as subprocesses, `news-recap create` removes vendor API keys
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
> news-recap create --use-api-key
> ```

- `NEWS_RECAP_LLM_DEFAULT_AGENT` — default agent (`codex`, `claude`, or `gemini`).
- `NEWS_RECAP_LLM_TASK_MODEL_MAP` — per-task-type model overrides by agent
  (`task_type:agent=model_flags,...`).

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap create --help
news-recap prompt --help
news-recap info --help
news-recap list --help
news-recap delete --help
news-recap serve --help
news-recap configure --help
news-recap schedule --help
news-recap schedule set --help
```
