[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, deduplicating news
and producing daily recaps with LLM agents orchestrated by [Prefect](https://www.prefect.io/).

The key idea: instead of paying per-token via expensive LLM APIs, the pipeline drives
CLI agents (Codex, Claude Code, Gemini CLI) that run under flat-rate ~$20/month
subscriptions — making heavy daily summarisation practically free.

### Documentation

- [News Recap](https://andgineer.github.io/news-recap/)

### User defaults

- Local runs use `user_id=default_user`.
- You can override context with:
  - `NEWS_RECAP_USER_ID`
  - `NEWS_RECAP_USER_NAME`

# Developers

For development you need [uv](https://github.com/astral-sh/uv) installed.

Bootstrap the environment and install pre-commit hooks:

    source ./activate.sh
    pre-commit install

Run all checks:

    uv run inv pre

## Prefect server (optional)

By default the recap pipeline runs in **ephemeral** mode (no server required).
To get the Prefect UI with flow/task observability, start a local server:

    prefect server start

Then point the pipeline at it:

    export PREFECT_API_URL=http://localhost:4200/api
    export NEWS_RECAP_PREFECT_MODE=server   # or "auto" to probe and fall back

Open the dashboard at <http://localhost:4200>.

Available modes (`NEWS_RECAP_PREFECT_MODE`):

| Value       | Behaviour                                                        |
|-------------|------------------------------------------------------------------|
| `ephemeral` | *(default)* Run locally, no server needed                        |
| `server`    | Require `PREFECT_API_URL`; fail fast if unreachable              |
| `auto`      | Probe `PREFECT_API_URL`; fall back to ephemeral if unreachable   |

## Allure test report

* [Allure report](https://andgineer.github.io/news-recap/builds/tests/)

# Scripts

Install [invoke](https://docs.pyinvoke.org/en/stable/) preferably with [pipx](https://pypa.github.io/pipx/):

    pipx install invoke

For a list of available scripts run:

    invoke --list

For more information about a script run:

    invoke <script> --help

## Coverage report

* [Codecov](https://app.codecov.io/gh/andgineer/news-recap/tree/main/src%2Fnews_recap)
* [Coveralls](https://coveralls.io/github/andgineer/news-recap)

> Created with cookiecutter using [template](https://github.com/andgineer/cookiecutter-python-package)
