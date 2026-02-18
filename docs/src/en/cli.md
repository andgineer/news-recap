# CLI (Current MVP)

In Epic 1, the product is operated through CLI commands.

## Main Command

Run one ingestion cycle:

```bash
news-recap ingest daily
```

Common options:

- `--db-path PATH` — SQLite file path.
- `--feed-url TEXT` — RSS/Atom feed URL (repeatable).

If `--feed-url` is not provided, feeds are read from:

- `NEWS_RECAP_RSS_FEED_URLS` (comma-separated),
- optionally `NEWS_RECAP_RSS_FEED_URL`.

## How to Get an Inoreader RSS URL

1. In Inoreader, open the folder or tag (label) you want to ingest.
2. Open that folder/tag menu and find the RSS publishing option
   (`Create output feed`, `Output RSS`, or a similar label).
3. Create the output feed and copy the generated URL like
   `https://www.inoreader.com/stream/user/...`.
4. Pass this URL to the app:

```bash
export NEWS_RECAP_RSS_FEED_URLS="https://www.inoreader.com/stream/user/..."
news-recap ingest daily
```

Important:
- Output feed URLs are usually personal. Do not expose them publicly.
- You do not need to manually add `?n=...` to the URL. The app appends item limits via
  `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED` (default `10000`) or
  `NEWS_RECAP_RSS_FEED_ITEMS` for per-feed overrides.

## Observability Commands

Show run and dedup stats:

```bash
news-recap ingest stats --hours 24
```

Inspect clusters:

```bash
news-recap ingest clusters --hours 24 --limit 20
news-recap ingest clusters --run-id <run_id> --show-members
```

Inspect duplicate examples:

```bash
news-recap ingest duplicates --hours 24 --limit-clusters 10
news-recap ingest duplicates --run-id <run_id>
```

## Helpful Environment Variables

- `NEWS_RECAP_DB_PATH`
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED`
- `NEWS_RECAP_RSS_FEED_ITEMS` (`<feed_url>|<items>,...`)
- `NEWS_RECAP_DEDUP_MODEL_NAME`

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap ingest daily --help
news-recap ingest stats --help
news-recap ingest clusters --help
news-recap ingest duplicates --help
```
