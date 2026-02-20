# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
source ./activate.sh                          # bootstrap .venv with uv, activate it
uv sync --frozen                              # install locked dependencies
uv run pytest --cov=src tests/                # run all tests with coverage
uv run pytest tests/test_cleaning.py::test_fn # run a single test
invoke pre                                    # pre-commit (ruff, pyrefly, formatting)
pre-commit run --verbose --all-files          # same, explicit form
news-recap --help                             # CLI entrypoint after install
```

Stress tests run in CI with `NEWS_RECAP_RUN_STRESS_TESTS=1` and `NEWS_RECAP_STRESS_ITERATIONS=500`.

`pytest.ini` enables `--doctest-modules` — docstring examples must stay executable.

## Architecture

Two subsystems share one SQLite database (`.news_recap.db`, configurable via `NEWS_RECAP_DB_PATH`):

### Ingestion Pipeline (`src/news_recap/ingestion/`)
RSS feeds → `RssSourceAdapter` (HTTP cache, pagination, defusedxml) → `FetchStageService` → `ArticleNormalizationService` (HTML cleaning, language detection) → `SQLiteRepository` (articles + user_articles) → `DedupStageService` (sentence-transformers embeddings → cosine-similarity clustering).

Entry point: `IngestionOrchestrator.run_daily()` in `pipeline.py`.

### LLM Orchestrator (`src/news_recap/orchestrator/`)
Task queue system that enqueues LLM tasks → materializes per-task workdirs with JSON contracts → executes external CLI agents (`codex`/`claude`/`gemini`) as subprocesses → validates JSON output → persists results. Worker uses claim-execute-validate-commit cycle with failure classification and retry.

Agents use a **manifest-native** contract: the enriched prompt points the agent to `task_manifest.json`, which contains paths to all input/output files. Agents discover articles, write output JSON, and reference `source_ids` from the articles index — no IDs or file contents are passed on the command line.

Backend capability is policy-controlled via `NEWS_RECAP_BACKEND_CAPABILITY_MODE`: `manifest_native` (default, strict JSON contract) or `stdout_parser_fallback` (opt-in recovery from stdout).

Token usage is extracted from agent stdout/stderr (`usage.py`) and cost estimated via configurable pricing (`pricing.py`, `NEWS_RECAP_LLM_PRICING` env var).

Entry point: `OrchestratorWorker.run()` in `worker.py`.

**Intelligence layer** (`intelligence.py`): higher-level flows — stories, highlights, monitors, Q&A — that produce tasks for the orchestrator.

Agent CLI command templates, model mappings, and troubleshooting: `dev/agent-setup.md`.

### Key Patterns
- **CLI-first, no HTTP API.** Commands go through `*CliController` classes that accept `*Command` dataclasses and return `Iterator[str]`.
- **Repository pattern.** `SQLiteRepository` (ingestion) and `OrchestratorRepository` (orchestrator) own all SQL. No raw SQL in business logic.
- **File-based contracts** (`contracts.py`): task I/O uses JSON files in per-task workdirs managed by `TaskWorkdirManager`. Manifest-native: agents read `task_manifest.json` to discover all paths.
- **Routing** (`routing.py`): `FrozenRouting` resolves agent + profile (fast/quality) → concrete model at enqueue time.
- **Optimistic concurrency** in repository: state transitions use `WHERE status = :expected` guards; rejected transitions emit `state_transition_rejected` events.
- **All settings** via `Settings.from_env()` in `config.py` (dataclass + env vars, no config files).
- **Alembic migrations** run programmatically via `AlembicRunner` at startup.

## Coding Conventions

- Python 3.12+, type hints on public functions, `dataclasses` with `slots=True`.
- `snake_case` functions/vars, `UPPER_CASE` constants, `CapWords` classes.
- Ruff enforces formatting (~100 char lines) and linting; pyrefly for type checking.
- Target 85%+ test coverage. Tests use `pytest` with `click.testing` for CLI tests.
- Commit messages: short, imperative, one logical change per commit.
