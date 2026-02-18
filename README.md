[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, and deduplicating news into
structured daily inputs for later highlights, stories, and Q&A stages.

## Epic 1 MVP (Current)

Epic 1 is already usable with real data from RSS feeds (including Inoreader Output RSS).

### Implemented now

- RSS/Atom ingestion with pagination, retry/backoff, and gap tracking for transient failures.
- Article normalization and HTML-to-text cleaning with bounded text size.
- Semantic deduplication before downstream LLM stages.
- Persistent SQLite storage for runs, raw payloads, normalized articles, embeddings, and dedup artifacts.
- Single-tenant, multi-user-ready schema and repository contracts.
- Automatic local bootstrap of `default_user`.

### Usage

- [News Recap](https://andgineer.github.io/news-recap/)

### User defaults

- Local runs use `user_id=default_user`.
- You can override context with:
  - `NEWS_RECAP_USER_ID`
  - `NEWS_RECAP_USER_NAME`

### MVP boundary

Epic 1 covers ingestion and dedup foundation only.
Highlights generation, story assembly, Telegram delivery, and interactive Q&A are planned for
later epics.

# Developers

Do not forget to run `source ./activate.sh`.

For development you need [uv](https://github.com/astral-sh/uv) installed.

Use [pre-commit](https://pre-commit.com/#install) hooks for code quality:

    pre-commit install

Run all checks:

    source ./activate.sh && pre-commit run --verbose --all-files --

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
