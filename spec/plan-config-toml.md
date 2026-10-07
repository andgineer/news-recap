# Plan: Settings in `config.toml`

Status: done (2026-10-07).

## Goal

news-recap is a desktop tool installed with `pip`/`uv tool install`, not a server: settings
belong in a file the user owns, not in environment variables. A user who never cloned the repo
sets everything with one command, and the file keeps up with new releases' defaults.

## Decisions

1. **One file:** `<data_dir>/config.toml` (default `~/.news_recap_data/config.toml`). A missing
   file means release defaults; loading never writes it.
2. **Environment variables are for secrets and bootstrap only:** `TYPESAFE_API_KEY` (also read
   from `./.env` and `<data_dir>/.env`, never exported) and the API-mode agent keys,
   `NEWS_RECAP_DATA_DIR` (where the file lives; tests), and the dev-only switches
   `NEWS_RECAP_STOP_AFTER` and `NEWS_RECAP_CLASSIFY_MAX_BATCHES`. Every other `NEWS_RECAP_*`
   setting is gone, with no migration (one installation exists).
3. **Top-level keys are the everyday settings:** `language`, `exclude`, `follow`, `agent`,
   `rss`, `classify_backend`, `dedup_backend`. `exclude` and `follow` are multi-line strings,
   one topic per line. Enum keys carry a comment listing their values.
4. **Advanced keys live in sections** (`[ingestion]`, `[fetch]`, `[dedup]`, `[llm]`, `[api]`)
   and are written commented out with this release's default, so the app follows each
   release's defaults until the user uncomments a line. RSS fetch knobs are `[fetch]`: a
   top-level `rss` key and an `[rss]` table cannot coexist in TOML.
5. **`news-recap config`** creates the file from the template when missing and shows the path
   and the top-level values; `news-recap config set KEY VALUE…` edits a top-level key with
   `tomlkit` (comments and layout kept). Advanced keys are edited by hand. The interactive
   `configure` command and `config.json` are removed.
6. **CLI flags override the file for one run** (`--agent`, `--rss`, `--language`, …).
7. **Defaults:** agent `antigravity` (free tier, no keys), both Jev backends `llm`.
8. **Validation:** an unknown key, a wrong type or a value outside its choices stops the run
   with a one-line error naming the key and the file (no traceback), for every command.
9. **Schedule:** `schedule set` bakes `--rss`/`--agent` into the run script only when given, so
   scheduled runs follow the file.
10. **Exclude topics split on commas and line breaks** at parenthesis depth 0, so one topic per
    line needs no commas.
11. Dead settings are deleted, not moved: the queue-worker knobs (`worker_id`, poll interval,
    retry base/max, stale-attempt and graceful-shutdown seconds) and `api_timeout_seconds`.

## Implementation

- `src/news_recap/config_file.py`: key table (section, key, settings field, type, choices,
  comment), template rendering from the dataclass defaults, `load_config_file`,
  `set_config_value` (tomlkit, atomic write).
- `config.py`: `Settings.load(execution_backend=None)` replaces `Settings.from_env`;
  `Settings.preferences` (language, exclude, follow); Jev backends from the file; validation
  messages name config keys.
- `main.py`: `config` group (show, `set`); `ingest`/`schedule set` take feeds from the file when
  `--rss` is not given; remove `configure`, `operation_configure.py`, `user_config.py`.
- `launcher.py`, `export_prompt.py`: preferences from `Settings`, CLI overrides on top.
- `recap/jev/policy.py`: split on line breaks too.
- Tests: autouse fixture points `NEWS_RECAP_DATA_DIR` at a temp dir; settings tests write a
  `config.toml` there; new tests for the template, load errors and `config set`.
- Docs: README and `docs/src/{en,ru}` quick start (agy, `config set rss`, ingest, create,
  serve; Jev optional), a `config.toml` reference replacing the env-var lists;
  `spec/agents.md`, `CLAUDE.md`, `spec/plan-jev-decisions.md`.
- Author's machine: write `config.toml` (feed, antigravity, classify `jev`, dedup `llm`),
  drop the `NEWS_RECAP_*` lines from `<data_dir>/.env`, regenerate the schedule.

## Verification

```bash
uv run pytest --cov=src tests/
inv pre
NEWS_RECAP_DATA_DIR=$(mktemp -d) news-recap config      # writes and shows the template
NEWS_RECAP_DATA_DIR=... news-recap config set rss https://example.com/feed.xml
```
