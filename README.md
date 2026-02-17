[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, and deduplicating news into
structured daily inputs for later highlights, stories, and Q&A stages.

## Epic 1 MVP (Current)

Epic 1 is already usable with real data from RSS feeds (including Inoreader Output RSS).

### Implemented now

- RSS/Atom ingestion with pagination, retry/backoff, and gap tracking for transient failures.
- Article normalization and HTML-to-text cleaning with bounded text size.
- Semantic deduplication before downstream LLM stages.
- Persistent SQLite storage for runs, raw payloads, normalized articles, embeddings, and dedup artifacts.
- Single-tenant, multi-user-ready schema and repository contracts.
- Automatic local bootstrap of `default_user`.

### Run with real data

1. Activate the environment:

```bash
source ./activate.sh
```

2. Configure RSS feed URL(s):

```bash
export NEWS_RECAP_RSS_FEED_URLS="https://www.inoreader.com/stream/user/100.../tag/news?output=rss,https://example.com/another.xml"
```

3. Run ingestion:

```bash
uv run news-recap ingest daily
```

Optional:

```bash
uv run news-recap ingest daily --db-path /path/to/news_recap.db
uv run news-recap ingest daily --feed-url "https://www.inoreader.com/stream/user/100.../tag/news?output=rss"
```

### Expected CLI result

The command prints one run summary with:

- `run_id`, `status`
- `ingested`, `updated`, `skipped`
- `clusters`, `duplicates`
- `gaps`

### Inspect ingestion quality from CLI

Get 24h window stats (ingested/updated/skipped, dedup duplicates, clusters):

```bash
uv run news-recap ingest stats --hours 24
```

Inspect cluster sizes for a run (or latest run in lookback window):

```bash
uv run news-recap ingest clusters --hours 24 --limit 20
uv run news-recap ingest clusters --run-id <run_id> --show-members
```

Show duplicate examples with article samples from the same cluster:

```bash
uv run news-recap ingest duplicates --hours 24 --limit-clusters 10
uv run news-recap ingest duplicates --run-id <run_id>
```

### Inspect results in SQLite

```bash
sqlite3 .news_recap.db "SELECT run_id,status,ingested_count,updated_count,skipped_count,dedup_clusters_count,dedup_duplicates_count,gaps_opened_count FROM ingestion_runs ORDER BY started_at DESC LIMIT 5;"
sqlite3 .news_recap.db "SELECT COUNT(*) FROM articles;"
```

### User defaults

- Local runs use `user_id=default_user`.
- You can override context with:
  - `NEWS_RECAP_USER_ID`
  - `NEWS_RECAP_USER_NAME`

### MVP boundary

Epic 1 covers ingestion and dedup foundation only.
Highlights generation, story assembly, Telegram delivery, and interactive Q&A are planned for
later epics.

# Documentation

[News Recap](https://andgineer.github.io/news-recap/)

# Developers

Do not forget to run `source ./activate.sh`.

For development you need [uv](https://github.com/astral-sh/uv) installed.

Use [pre-commit](https://pre-commit.com/#install) hooks for code quality:

    pre-commit install

Run all checks:

    source ./activate.sh && pre-commit run --verbose --all-files --

## Allure test report

* [Allure report](https://andgineer.github.io/news-recap/builds/tests/)

# Scripts

Install [invoke](https://docs.pyinvoke.org/en/stable/) preferably with [pipx](https://pypa.github.io/pipx/):

    pipx install invoke

For a list of available scripts run:

    invoke --list

For more information about a script run:

    invoke <script> --help

## Coverage report

* [Codecov](https://app.codecov.io/gh/andgineer/news-recap/tree/main/src%2Fnews_recap)
* [Coveralls](https://coveralls.io/github/andgineer/news-recap)

> Created with cookiecutter using [template](https://github.com/andgineer/cookiecutter-python-package)
