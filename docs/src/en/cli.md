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

## LLM Agent Smoke Checks

Run direct checks (without DB queue):

```bash
news-recap llm smoke
```

Force specific agents:

```bash
news-recap llm smoke --agent codex --agent claude --agent gemini
```

Switch model profile (`fast` vs `quality`) at runtime:

```bash
news-recap llm smoke --agent codex --model-profile quality
news-recap llm smoke --agent claude --model-profile fast
```

Use a concrete model override:

```bash
news-recap llm smoke --agent codex --model gpt-5-codex-mini
```

Default command templates (fixed from research run on February 18, 2026):

- `codex`: `codex exec --sandbox workspace-write -c sandbox_workspace_write.network_access=true -c model_reasoning_effort=high --model {model} {prompt}`
- `claude`: `claude -p --model {model} --permission-mode dontAsk --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" -- {prompt}`
- `gemini`: `gemini --model {model} --approval-mode auto_edit --prompt {prompt}`

For Gemini file+web tasks in non-interactive mode, use this safer explicit template:

```bash
NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE='gemini --model {model} --approval-mode auto_edit --include-directories . --allowed-tools read_file,write_file,replace,web_fetch,list_directory --prompt {prompt}'
```

You can override them with:

- `NEWS_RECAP_LLM_DEFAULT_AGENT`
- `NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP` (`highlights=fast,story=quality,qa=fast`)
- `NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_CLAUDE_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_CODEX_MODEL_FAST` / `NEWS_RECAP_LLM_CODEX_MODEL_QUALITY`
- `NEWS_RECAP_LLM_CLAUDE_MODEL_FAST` / `NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY`
- `NEWS_RECAP_LLM_GEMINI_MODEL_FAST` / `NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY`

Note:
- `codex` default stays sandboxed (`workspace-write`) and does not use `danger-full-access`.
- Network is enabled explicitly via `sandbox_workspace_write.network_access=true` so file+web tasks
  work in non-interactive CLI runs.
- `antigravity` is not supported in non-interactive orchestrator runtime.
- Model IDs and command flags are known-good defaults as of February 18, 2026; if provider CLIs
  change, update them through env overrides.
- Gemini non-interactive mode in this project uses Gemini CLI auth session; `GEMINI_API_KEY`
  is not required for the default CLI flow.

### Automated Model Refresh Runbook

When to run model refresh:

- immediately if error class is `model_not_available`;
- immediately if smoke fails for the same `agent/profile` twice in a row;
- after CLI agent version change (`codex --version`, `claude --version`, `gemini --version`);
- planned weekly.

When **not** to change model mapping:

- `access_or_auth` errors;
- `billing_or_quota` errors.
- probe/runtime timeout errors (`Probe timed out`, `Synthetic task timed out`).

In these cases, fix auth or billing first.

Recommended maintenance prompt for an agent:

```text
You are the LLM model-maintenance agent for this repo.

Goal:
Validate current model routing for codex/claude/gemini and update model mappings only if needed.

Rules:
1) Work only in this repo.
2) Run smoke matrix for agents x profiles (fast, quality).
3) Treat auth/quota failures as non-model issues; do NOT change model mapping for them.
4) Change mapping only when failure indicates model drift (not found/deprecated/unsupported).
5) After each candidate change, re-run smoke for that exact agent/profile.
6) Keep edits minimal and deterministic.

Commands to use:
- news-recap llm smoke --agent codex --model-profile fast
- news-recap llm smoke --agent codex --model-profile quality
- news-recap llm smoke --agent claude --model-profile fast
- news-recap llm smoke --agent claude --model-profile quality
- news-recap llm smoke --agent gemini --model-profile fast
- news-recap llm smoke --agent gemini --model-profile quality

If a model drift is confirmed:
- Update env defaults/mapping in config.
- Update docs with new known-good defaults.
- Update tests that assert defaults.
- Run:
  - uv run pytest -q
  - source ./activate.sh && pre-commit run --verbose --all-files --

Output:
1) A short report with before/after matrix.
2) Exact files changed.
3) Unresolved blockers (if any).
```

Watchdog script (recommended automation entrypoint):

```bash
scripts/model_watchdog.sh
scripts/model_watchdog.sh --run-refresh --refresh-agent codex
```

Exit codes:

- `0` checks passed (or refresh executed successfully);
- `10` refresh is recommended (triggers detected, `--run-refresh` not used);
- `11` refresh was attempted and failed;
- `12` blocking auth/quota/timeout failures detected.

## Retention Cleanup

Delete old user-linked articles by `discovered_at`:

```bash
news-recap ingest prune --days 30
```

Dry-run mode (no DB changes):

```bash
news-recap ingest prune --days 30 --dry-run
```

Automatic cleanup also runs after `news-recap ingest daily` when
`NEWS_RECAP_ARTICLE_RETENTION_DAYS > 0`.

## Helpful Environment Variables

- `NEWS_RECAP_DB_PATH`
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED`
- `NEWS_RECAP_RSS_FEED_ITEMS` (`<feed_url>|<items>,...`)
- `NEWS_RECAP_DEDUP_MODEL_NAME`
- `NEWS_RECAP_ARTICLE_RETENTION_DAYS`

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap ingest daily --help
news-recap ingest stats --help
news-recap ingest clusters --help
news-recap ingest duplicates --help
news-recap ingest prune --help
```
