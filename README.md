[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, deduplicating news
and producing daily recaps with LLM agents.

The pipeline drives CLI agents such as ChatGPT Codex, Claude Code, and Google Antigravity, so
it runs on flat-rate subscriptions.

Running it daily for 7 days consumes roughly 20% of the weekly Claude subscription
limit and less than that for ChatGPT / Google.

For comparison, Inoreader charges an additional \$19.90/month **on top** of
a Pro subscription for AI-powered aggregation.

> Start with the [Quick start](https://andgineer.github.io/news-recap/#quick-start).

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
