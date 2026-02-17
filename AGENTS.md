# Repository Guidelines

## Project Structure & Module Organization
- `src/news_recap/`: main package code. CLI entrypoint is `main.py`; package version lives in `__about__.py`.
- `tests/`: pytest test suite (including CLI checks).
- `docs/`: MkDocs content, with language folders under `docs/src/en/` and `docs/src/ru/`.
- `scripts/`: helper scripts for docs, version bumps, packaging, and uploads.
- `tasks.py`: Invoke task definitions (`pre`, `ver-release`, `docs-en`, etc.).

## Build, Test, and Development Commands
- `./activate.sh`: activate the local development environment used by this repo.
- `uv sync --frozen`: install locked dependencies from `uv.lock`.
- `uv run pytest --cov=src tests/`: run tests with coverage (mirrors CI intent).
- `pre-commit run --verbose --all-files`: run lint/format/type checks locally.
- `invoke pre`: shortcut to run pre-commit checks.
- `invoke --list`: list available automation tasks.
- `./scripts/build-docs.sh`: build documentation site for configured languages.
- `./scripts/build-docs.sh --copy-assets en` then `mkdocs serve -f docs/_mkdocs.yml`: local docs preview flow.

## Coding Style & Naming Conventions
- Python 3.10+ with 4-space indentation and explicit, readable names.
- Naming: `snake_case` for modules/functions/variables, `UPPER_CASE` for constants, `CapWords` for classes.
- Use type hints for public functions and CLI-related logic where practical.
- Formatting and linting are enforced through pre-commit with Ruff; run hooks before pushing.
- Keep line length formatter-friendly (Ruff hooks are configured for ~100 chars).

## Testing Guidelines
- Framework: `pytest` (with `click.testing` for CLI behavior tests).
- Test files: `test_*.py`; test functions: `test_*`.
- `pytest.ini` enables doctests (`--doctest-modules`), so doc examples must remain executable.
- CI publishes coverage reports/comments; target at least 85% total coverage to stay in the green band.

## Commit & Pull Request Guidelines
- Keep commit messages short and imperative, consistent with existing history (for example, `pre-commit`, `Version v0.0.1`).
- Prefer one logical change per commit.
- PRs should include: purpose, summary of changes, test commands run, and linked issue(s) when applicable.
- Update docs (`README.md` and `docs/`) in the same PR when behavior or CLI usage changes.
