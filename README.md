[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, deduplicating news
and producing daily recaps with LLM agents.

The key idea: instead of paying per-token via expensive LLM APIs, the pipeline drives
CLI agents (Codex, Claude Code, Gemini CLI) that run under flat-rate ~$20/month
subscriptions — making heavy daily summarisation practically free.

## CLI agents vs direct API — benchmark

Same 423 articles, Claude, two modes:

| | CLI agent (`claude`)   | API (`--api`)          |
|---|------------------------|------------------------|
| Cost | ~$0.25 (~$7 per month) | \$0.43 ($13 per month) |
| Time | 21 min                 | 8 min                  |
| Output blocks | 100                    | 105                    |
| Sections | 20                     | 23                     |
| Summary length | ~1.5 K                 | ~2 K                   |

CLI agent used Sonnet for all tasks (Haiku unavailable in the subscription CLI) — that
partially explains the longer runtime and visibly better compression quality.
API mode uses cheap Haiku for most tasks and Sonnet only for the reduce phase, which
is why it's faster and cheaper but produces slightly looser output.

Another CLI overhead: agents are external processes, so each task pays a cold-start
penalty that adds up across hundreds of parallel calls.

Using subscription twice as cheeper but still too expensive for dayly usage - from $20 subscription 
one run takes 5% from week limit, and 46% from 5h limit.

### Documentation

- [News Recap](https://andgineer.github.io/news-recap/)

## Architecture

- [Pipeline spec](spec/pipeline.md) — per-step contracts, state flow, and checkpointing for the recap pipeline.

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
