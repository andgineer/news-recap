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
- `config`: show the settings file (created on first use); `config set` changes a setting.
- `schedule set`: install or update the daily scheduled digest job.
- `schedule get`: show current schedule configuration.
- `schedule delete`: remove the daily scheduled digest job.

## Common Notes

- Settings live in `config.toml` in the data directory; see [`config`](#config).
- The data directory is `~/.news_recap_data`; the `NEWS_RECAP_DATA_DIR` environment variable
  points elsewhere.
- Data is stored as JSON files with daily partitioning; old partitions are
  garbage-collected automatically after `ingestion.retention_days`.

## Ingestion

### `ingest`
Run one ingestion cycle from RSS/Atom feeds.

```bash
news-recap ingest
news-recap ingest --rss https://example.com/feed.xml
```

Key options:
- `--rss` (repeatable)

If `--rss` is omitted, the feeds come from `rss` in `config.toml`
(`news-recap config set rss URL [URL …]`).

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
- `--agent` (`codex`, `claude`, or `antigravity`)
- `--limit` (cap number of articles loaded)
- `--max-days` (max days to look back for articles; default `ingestion.lookback_days`
  in `config.toml`, 2)
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
as articles, `ingestion.retention_days` in `config.toml`).

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

### `config`
Show your settings, or change one. The settings file is `config.toml` in the data directory
(`~/.news_recap_data/config.toml`); the first `news-recap config` writes it with release
defaults.

```bash
news-recap config                                   # show the file path and the settings
news-recap config set rss https://example.com/feed.xml https://example.org/rss
news-recap config set language en
news-recap config set agent claude                  # antigravity | codex | claude
news-recap config set exclude "horoscopes" "sports (except Russia)"
news-recap config set classify_backend jev          # llm | jev
```

`config set` edits these keys: `language`, `exclude`, `follow`, `agent`, `rss`,
`classify_backend`, `dedup_backend`. `exclude` and `follow` take one topic per argument and are
stored one per line; a note in parentheses is an exception ("sports (except Russia)"). Comments
and anything else in the file are kept.

The rest of `config.toml` is advanced settings, written commented out with the current
release's default: the app follows each new release's defaults until you uncomment a line and
change it. See the [settings reference](#config-toml).

Priority (highest wins): CLI flags (`--rss`, `--agent`, `--language`), then `config.toml`, then
release defaults.

## API Mode

By default the digest pipeline runs LLM tasks by spawning CLI agent subprocesses
(`codex`, `claude`, `antigravity`). **API mode** replaces subprocess calls with direct
Anthropic SDK calls — no CLI agents required.

> API mode v1 supports Anthropic only. Codex and Antigravity are CLI-only for now.

### Quickstart

```bash
export ANTHROPIC_API_KEY=sk-ant-...
news-recap create --api
```

`--api` sets the API backend and the `claude` agent for that run.

### Per-task model map

By default, cost-sensitive tasks use `claude-haiku-4-5-20251001`, while
`recap_merge_sections` uses `claude-sonnet-5`. Override single tasks in the `[api]` section of
`config.toml`:

```toml
[api]
model_map.recap_merge_sections = "claude-sonnet-5"
```

### API mode settings {#api-settings}

In the `[api]` section of `config.toml`:

- `max_parallel` — initial concurrency cap (default `5`). Automatically downshifted on
  rate-limit errors and recovered after consecutive successes.
- `concurrency_recovery_successes` — consecutive successes needed to raise the cap by 1 after
  a downshift (default `10`).
- `retry_max_backoff_seconds` — exponential backoff ceiling (default `60`).
- `retry_jitter_seconds` — uniform jitter added to each backoff (default `5`).
- `downshift_pause_seconds` — extra pause after a rate-limit downshift before the next slot
  acquire (default `2`).

`llm.execution_backend = "api"` (with `agent = "claude"`) makes API mode the default.

## Scheduled Runs

See [Scheduled Runs](automation.md) for setup, platform details, logs, and troubleshooting.

## Settings reference (config.toml) {#config-toml}

Everyday keys (also settable with `news-recap config set`):

- `language` — digest language, a BCP-47 code (`en`, `ru`, `sr`, …). Default `ru`.
- `exclude` — topics to drop, one per line. Phrase them as subjects ("Croatian domestic news",
  not "Croatian news"): Jev reads topics literally.
- `follow` — topics that get their own sections, one per line.
- `agent` — `antigravity` (free Gemini tier, no keys; default), `codex` or `claude`.
- `rss` — feed URLs.
- `classify_backend`, `dedup_backend` — `llm` (default) or `jev`; see
  [Jev](index.md#optional-jev).

Advanced sections, written commented out with the release defaults:

- `[ingestion]` — `lookback_days` (max days of articles in a digest, default 2; by default the
  window starts at the last digest, `--all` uses the full window), `retention_days` (days of
  article partitions kept, default 7), `page_size`, `max_pages`, `backfill_max_gaps`,
  `clean_text_max_chars`, `min_resource_chars`.
- `[fetch]` — RSS fetching: `default_items_per_feed`, `per_feed_items`
  (`{ "https://…" = 500 }`), `snapshot_max_age_hours`, `max_retries`,
  `retry_backoff_seconds`, `request_timeout_seconds`.
- `[dedup]` — `threshold` (embedding similarity of a candidate group, default 0.9),
  `model_name`.
- `[llm]` — `workdir_root`, `execution_backend` (`cli` | `api`), and model flags per task and
  agent: `models.recap_classify.claude = "--model haiku"`.
- `[api]` — see [API mode settings](#api-settings).

Environment variables are only for secrets and the data directory:

- `NEWS_RECAP_DATA_DIR` — data directory (default `~/.news_recap_data`).
- `TYPESAFE_API_KEY` — the Jev key; also read from `.env` in the current directory or the data
  directory.
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTIGRAVITY_API_KEY` — agent API keys (see below).

> **Subscription vs API billing.** When spawning CLI agents (`claude`, `codex`, `antigravity`)
> as subprocesses, `news-recap create` removes vendor API keys
> (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTIGRAVITY_API_KEY`)
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
news-recap config --help
news-recap schedule --help
news-recap schedule set --help
```
