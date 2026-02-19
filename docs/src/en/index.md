# news-recap

`news-recap` is a CLI-first system for:

- collecting news from RSS/Atom feeds,
- normalizing and cleaning article text,
- semantic deduplication and clustering,
- running queue-based LLM tasks,
- generating story/highlights/Q&A outputs,
- tracking read-state and feedback,
- storing history and artifacts in SQLite.

## Current Scope

- Source ingestion from RSS/Atom feeds (including Inoreader Output RSS).
- Shared article storage with user-scoped retrieval.
- Queue worker runtime for external CLI agents.
- Story assignment, highlights generation, monitor answers, ad-hoc QA.
- Domain output persistence and observability commands.

## Where To Start

- Installation and environment setup: `installation.md`
- Full CLI commands and examples: `cli.md`

## Advanced

Use:

```bash
news-recap --help
```

for the complete command tree.
