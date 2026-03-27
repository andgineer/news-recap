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
- Recap pipeline with two modes:
    - **Map-reduce** (default): classify → load_resources → enrich → deduplicate → map → reduce → split → group_sections → summarize.
    - **Oneshot** (`--oneshot`): classify → load_resources → enrich → deduplicate → oneshot_digest (parallel batches + deterministic block dedup + section merge) → refine_layout (optional LLM pass to consolidate fragmented sections).

## Where To Start

- Installation and environment setup: `installation.md`
- Full CLI commands and examples: `cli.md`

## Advanced

Use:

```bash
news-recap --help
```

for the complete command tree.
