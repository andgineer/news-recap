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

Two subsystems share a file-based data directory (`.news_recap_data/`, configurable via `NEWS_RECAP_DATA_DIR`):

### Ingestion Pipeline (`src/news_recap/ingestion/`)
RSS feeds → `RssSourceAdapter` (HTTP cache, pagination, defusedxml) → `FetchStageService` → `ArticleNormalizationService` (HTML cleaning, language detection) → `IngestionStore` (daily-partitioned JSON files) → `DedupStageService` (sentence-transformers embeddings → cosine-similarity clustering).

Entry point: `run_daily_ingestion()` in `pipeline.py`.

### Recap Pipeline (`src/news_recap/recap/`)
Prefect-orchestrated pipeline: classify → enrich → group → deep-enrich → synthesize → compose.
Materializes per-task workdirs with JSON contracts → executes external CLI agents (`codex`/`claude`/`gemini`) as subprocesses → validates JSON output.

Subpackages:
- **`tasks/`** — pipeline step implementations (`Classify`, `Enrich`, `Group`, etc.) subclassing `TaskLauncher`, plus prompt templates.
- **`agents/`** — LLM agent execution (`ai_agent.py`), subprocess runner, routing resolution, mock agents (`echo.py`, `benchmark.py`).
- **`storage/`** — workdir materialization (`workdir.py`), pipeline I/O (`pipeline_io.py`), output schemas.
- **`loaders/`** — resource loading (HTTP fetch + text extraction for article enrichment).

Entry point: `recap_flow()` in `flow.py`, launched via `RecapCliController` in `launcher.py`.

### Storage (`src/news_recap/storage/`)
All persistence uses `msgspec.Struct` models serialized to JSON files via `storage/io.py`. No SQL database.

- **Daily article partitions**: `articles-YYYY-MM-DD.json` — auto-GC on startup deletes partitions older than `gc_retention_days`.
- **Feed state**: `feeds.json` — RSS HTTP cache and processing snapshots.
- **Run history**: `runs.json` — recent ingestion runs, gaps, dedup results.
- **Digest checkpoint**: `digest.json` — pipeline state saved after each phase for restart.
- **Atomic writes**: write-to-temp + rename pattern via `atomic_write()`.

### Key Patterns
- **CLI-first, no HTTP API.** Commands go through `*CliController` classes that accept `*Command` dataclasses and return `Iterator[str]`.
- **`IngestionStore`** (`ingestion/repository.py`) owns all file I/O for ingestion. No raw file access in business logic.
- **`msgspec.Struct`** for all domain models — same struct is used for storage, pipeline transfer, and agent serialization. No `to_dict()`/`from_dict()` boilerplate.
- **File-based contracts** (`contracts.py`): task I/O uses JSON files in per-task workdirs managed by `TaskWorkdirManager`.
- **Routing** (`agents/routing.py`): `FrozenRouting` resolves agent + profile (fast/quality) → concrete model.
- **All settings** via `Settings.from_env()` in `config.py` (dataclass + env vars, no config files).

## Coding Conventions

- Python 3.13+, type hints on public functions, `msgspec.Struct` for domain models, `dataclasses` for mutable counters.
- `snake_case` functions/vars, `UPPER_CASE` constants, `CapWords` classes.
- Ruff enforces formatting (~100 char lines) and linting; pyrefly for type checking.
- Target 85%+ test coverage. Tests use `pytest` with `click.testing` for CLI tests.
- Commit messages: short, imperative, one logical change per commit.
