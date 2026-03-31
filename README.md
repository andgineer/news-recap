[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, deduplicating news
and producing daily recaps with LLM agents.

Instead of throwing raw headlines into one oversized prompt, `news-recap` processes
news through a layered recap workflow that reduces noise, groups related stories,
and produces a cleaner daily digest.

The pipeline drives CLI agents such as Codex, Claude Code, and Gemini CLI, so heavy
daily summarization can run on flat-rate subscriptions instead of per-token APIs.

> Start with the [Quick start](https://andgineer.github.io/news-recap/#quick-start).

## Cost

Each digest pipeline run consumes roughly 3-4% of the weekly CLI agent subscription
quota (~\$0.19 per run, ~\$6/month at daily use).

The dollar figures are approximate. The pipeline runs under flat-rate subscriptions
(Codex, Claude Code, Gemini CLI at ~\$20/month), so the quota would mostly go
unused anyway.

### Docs

- [Manual](https://andgineer.github.io/news-recap/)
- [Pipeline spec](spec/pipeline.md)

# Developers

For development you need [uv](https://github.com/astral-sh/uv) installed.

Bootstrap the environment and install pre-commit hooks:

    source ./activate.sh
    pre-commit install

Run all checks:

    uv run inv pre

## Allure test report

* [Allure report](https://andgineer.github.io/news-recap/builds/tests/)

# Scripts

Install [uv](https://github.com/astral-sh/uv) first. It is used both for package
installation and for development automation.

For a list of available scripts run:

    uv run invoke --list

For more information about a script run:

    uv run invoke <script> --help

## Coverage report

* [Codecov](https://app.codecov.io/gh/andgineer/news-recap/tree/main/src%2Fnews_recap)
* [Coveralls](https://coveralls.io/github/andgineer/news-recap)

> Created with cookiecutter using [template](https://github.com/andgineer/cookiecutter-python-package)
