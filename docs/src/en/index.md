# news-recap

`news-recap` is currently a CLI-first MVP for:

- collecting news from RSS/Atom feeds,
- normalizing and cleaning article text,
- semantic deduplication and clustering,
- storing run history and artifacts in SQLite.

This is the technical ingestion stage of the product. A non-CLI end-user experience is planned for
future iterations.

## Current Scope (Epic 1)

- Source: RSS/Atom feeds (including Inoreader Output RSS links).
- Storage: local SQLite (`.news_recap.db` by default).
- Output: ingestion runs, normalized articles, dedup clusters, duplicate samples.

## Where To Start

- Installation and environment setup: `installation.md`
- Current CLI commands and examples: `cli.md`

## Advanced

Use:

```bash
news-recap --help
```

to see all available commands.
