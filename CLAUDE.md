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

### Intelligence Layer (`src/news_recap/brain/`)
Synchronous Prefect `@flow` functions that run CLI LLM agents (`codex`/`claude`/`gemini`) via subprocess, validate JSON output, and persist results. Shared agent execution logic lives in `agent_runtime.py`.

Agents use a **manifest-native** contract: the prompt points the agent to `task_manifest.json`, which contains paths to all input/output files. Agents discover articles, write output JSON, and reference `source_ids` from the articles index.

Flows: highlights, story details, monitors, Q&A — all run synchronously and return results to the CLI.

Token usage is extracted from agent stdout/stderr (`usage.py`) and cost estimated via configurable pricing (`pricing.py`).

Entry point: `IntelligenceCliController` in `brain/flows.py`.

### Key Patterns
- **CLI-first, no HTTP API.** Commands go through `*CliController` classes that accept `*Command` dataclasses and return `Iterator[str]`.
- **Repository pattern.** `SQLiteRepository` owns all SQL (ingestion + intelligence). No raw SQL in business logic.
- **File-based contracts** (`contracts.py`): task I/O uses JSON files in per-task workdirs managed by `TaskWorkdirManager`. Agents read `task_manifest.json` to discover all paths.
- **Routing** (`routing.py`): `FrozenRouting` resolves agent + profile (fast/quality) → concrete model.
- **All settings** via `Settings.from_env()` in `config.py` (dataclass + env vars, no config files).
- **Alembic migrations** run programmatically via `AlembicRunner` at startup.

## Coding Conventions

- Python 3.12+, type hints on public functions, `dataclasses` with `slots=True`.
- `snake_case` functions/vars, `UPPER_CASE` constants, `CapWords` classes.
- Ruff enforces formatting (~100 char lines) and linting; pyrefly for type checking.
- Target 85%+ test coverage. Tests use `pytest` with `click.testing` for CLI tests.
- Commit messages: short, imperative, one logical change per commit.
