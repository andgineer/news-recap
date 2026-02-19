# CLI

`news-recap` is operated from CLI commands grouped by workflow stage.

## Command Map

- `ingest`: source import, stats, dedup inspection, retention cleanup.
- `llm`: task queue, worker runtime, retries, smoke checks, benchmark.
- `stories`: pinned story definitions and daily story assignment build.
- `highlights`: enqueue daily highlights generation.
- `story-details`: enqueue detailed output for one story.
- `monitors`: define/list/run scheduled monitor prompts.
- `qa`: enqueue ad-hoc question answering tasks.
- `read-state`: mark outputs/blocks as viewed/opened.
- `feedback`: attach like/dislike/hide/pin feedback.
- `insights`: domain-level stats and output listing.

## Common Notes

- Most commands support `--db-path` to point to a specific SQLite file.
- Source IDs must use format `article:<article_id>`.
- Queue tasks are executed by `news-recap llm worker`.

## Ingestion Commands

### `ingest daily`
Run one ingestion cycle from RSS/Atom feeds.

```bash
news-recap ingest daily
news-recap ingest daily --feed-url https://example.com/feed.xml
```

Key options:
- `--feed-url` (repeatable)
- `--db-path`

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

### `ingest prune`
Delete old user-article links by retention age (`discovered_at`).

```bash
news-recap ingest prune --days 30
news-recap ingest prune --days 30 --dry-run
```

Key options:
- `--days`
- `--dry-run/--no-dry-run`

### `ingest gc`
Delete globally unreferenced shared records.

```bash
news-recap ingest gc
news-recap ingest gc --dry-run
```

Key options:
- `--dry-run/--no-dry-run`

## LLM Queue Commands

### `llm enqueue-test`
Enqueue one queue task with optional routing overrides.

```bash
news-recap llm enqueue-test --task-type highlights --prompt "Top updates"
```

Key options:
- `--task-type`
- `--prompt`
- `--source-id` (repeatable)
- `--priority`
- `--agent`, `--model-profile`, `--model`
- `--max-attempts`, `--timeout-seconds`

### `llm worker`
Run queue worker once or in loop mode.

```bash
news-recap llm worker --once
news-recap llm worker --loop --max-tasks 100
```

### `llm stats`
Show queue health, validation/retry metrics, and latency.

```bash
news-recap llm stats --hours 24
```

### `llm failures`
List failed attempts with sanitized diagnostics.

```bash
news-recap llm failures --hours 24
news-recap llm failures --failure-class output_invalid_json --agent codex
```

Key options:
- `--hours`
- `--task-type`
- `--agent`
- `--model`
- `--failure-class`
- `--limit`

### `llm usage`
Show per-attempt usage telemetry for one task.

```bash
news-recap llm usage --task-id <task_id>
```

### `llm cost`
Show grouped token/cost summary for recent attempts.

```bash
news-recap llm cost --hours 24 --group-by model
news-recap llm cost --hours 24 --group-by agent
```

### `llm benchmark`
Run deterministic queue benchmark and write report.

```bash
news-recap llm benchmark --tasks-per-type 10
news-recap llm benchmark --task-type highlights --task-type qa --use-configured-agent
```

Key options:
- `--task-type` (repeatable)
- `--tasks-per-type`
- `--source-id` (repeatable)
- `--output`
- `--use-benchmark-agent/--use-configured-agent`

### `llm tasks`
List recent tasks, optionally filtered by status.

```bash
news-recap llm tasks --status queued --limit 50
```

### `llm inspect`
Show one task with event timeline.

```bash
news-recap llm inspect --task-id <task_id>
```

### `llm retry`
Manually re-queue failed/timeout/canceled task.

```bash
news-recap llm retry --task-id <task_id>
```

### `llm cancel`
Cancel queued/running task.

```bash
news-recap llm cancel --task-id <task_id>
```

### `llm smoke`
Run direct agent smoke checks without DB queue.

```bash
news-recap llm smoke
news-recap llm smoke --agent codex --model-profile quality
news-recap llm smoke --agent gemini --model gemini-2.5-flash
```

Key options:
- `--agent` (repeatable)
- `--model-profile` (`fast` or `quality`)
- `--model`
- `--prompt`, `--expect-substring`, `--timeout-seconds`
- `--claude-command`, `--codex-command`, `--gemini-command`

## Story and Output Generation Commands

### `stories define`
Create or update a pinned story definition.

```bash
news-recap stories define --name "Serbia updates" --description "Politics and economy" --target-language sr
```

Key options:
- `--story-id` (update existing)
- `--name`
- `--description`
- `--target-language`
- `--priority`
- `--enabled/--disabled`

### `stories list`
List pinned stories.

```bash
news-recap stories list
news-recap stories list --all
```

### `stories build`
Build pinned + auto assignments for one business date.

```bash
news-recap stories build
news-recap stories build --date 2026-02-18
```

### `highlights generate`
Enqueue highlights generation task for one date.

```bash
news-recap highlights generate --date 2026-02-18
```

Key options:
- `--date`
- `--priority`
- `--agent`, `--model-profile`, `--model`
- `--max-attempts`, `--timeout-seconds`

### `story-details generate`
Enqueue detailed generation for one pinned story.

```bash
news-recap story-details generate --story-id <story_id> --date 2026-02-18
```

Key options:
- `--story-id`
- `--date`
- routing/attempt/timeout options (same as highlights)

## Monitor and Q&A Commands

### `monitors define`
Create or update monitor prompt.

```bash
news-recap monitors define --name "Macro risks" --prompt "What changed in macro risk today?"
```

Key options:
- `--monitor-id` (update existing)
- `--name`
- `--prompt`
- `--cadence`
- `--enabled/--disabled`

### `monitors list`
List monitor definitions.

```bash
news-recap monitors list
news-recap monitors list --all
```

### `monitors run`
Enqueue monitor-answer tasks for enabled monitors.

```bash
news-recap monitors run --date 2026-02-18
```

Key options:
- `--date`
- routing/attempt/timeout options

### `qa ask`
Enqueue ad-hoc QA task with bounded retrieval context.

```bash
news-recap qa ask --prompt "What were the top geopolitical updates today?"
news-recap qa ask --prompt "What changed in energy markets?" --lookback-days 7
```

Key options:
- `--prompt`
- `--lookback-days`
- routing/attempt/timeout options

## Read-state and Feedback Commands

### `read-state mark`
Record read/open interaction for output or output block.

```bash
news-recap read-state mark --output-id <output_id> --event-type open
news-recap read-state mark --output-id <output_id> --event-type view --output-block-id 3
```

### `feedback add`
Attach feedback to output or one block.

```bash
news-recap feedback add --output-id <output_id> --feedback-type like
news-recap feedback add --output-id <output_id> --feedback-type hide --output-block-id 2
```

## Insights Commands

### `insights stats`
Show domain counters for stories, outputs, and engagement.

```bash
news-recap insights stats --hours 24
```

### `insights outputs`
List persisted business outputs.

```bash
news-recap insights outputs --limit 20
news-recap insights outputs --kind highlights --date 2026-02-18
```

## Important Environment Variables

- `NEWS_RECAP_DB_PATH`
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED`
- `NEWS_RECAP_RSS_FEED_ITEMS` (`<feed_url>|<items>,...`)
- `NEWS_RECAP_ARTICLE_RETENTION_DAYS`
- `NEWS_RECAP_LLM_DEFAULT_AGENT`
- `NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP`
- `NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_CLAUDE_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_CODEX_MODEL_FAST` / `NEWS_RECAP_LLM_CODEX_MODEL_QUALITY`
- `NEWS_RECAP_LLM_CLAUDE_MODEL_FAST` / `NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY`
- `NEWS_RECAP_LLM_GEMINI_MODEL_FAST` / `NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY`
- `NEWS_RECAP_LLM_PRICING` (`agent:model:input_per_1m:output_per_1m`, comma-separated)
- `NEWS_RECAP_QA_LOOKBACK_DAYS`
- `NEWS_RECAP_RETRIEVAL_TOP_K`
- `NEWS_RECAP_RETRIEVAL_MAX_ARTICLES`
- `NEWS_RECAP_RETRIEVAL_TOKEN_BUDGET`
- `NEWS_RECAP_RETRIEVAL_CHAR_BUDGET`

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap llm --help
news-recap stories --help
news-recap highlights --help
news-recap story-details --help
news-recap monitors --help
news-recap qa --help
news-recap read-state --help
news-recap feedback --help
news-recap insights --help
```
