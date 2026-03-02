# news-recap

`news-recap` is a CLI-first system for:

- collecting news from RSS/Atom feeds,
- normalizing and cleaning article text,
- semantic deduplication and clustering,
- producing daily digests with LLM agents (Codex, Claude Code, Gemini CLI),
- file-based article and digest storage.

## Current Scope

- Source ingestion from RSS/Atom feeds (including Inoreader Output RSS).
- File-based article storage with daily partitioning and automatic garbage collection.
- Recap pipeline: classify → load_resources → enrich → deduplicate → map → reduce → split → group_sections → summarize.

## Where To Start

- Installation and environment setup: `installation.md`
- Full CLI commands and examples: `cli.md`

## Advanced

Use:

```bash
news-recap --help
```

for the complete command tree.
