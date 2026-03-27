[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

`news-recap` is a CLI-first pipeline for collecting, cleaning, deduplicating news
and producing daily recaps with LLM agents.

The key idea: instead of paying per-token via expensive LLM APIs, the pipeline drives
CLI agents (Codex, Claude Code, Gemini CLI) that run under flat-rate ~$20/month
subscriptions — making heavy daily summarisation practically free.

## Pipeline modes — benchmark

All runs use Claude. Cost estimated from the \$20/month subscription limits.

| | Map-reduce CLI | Map-reduce API | Oneshot CLI |
|---|---|---|---|
| Articles | 703 | 423 | 703 |
| Time | 26 min | 8 min | 5–7 min |
| Blocks | 158 | 105 | 220–300 |
| Sections | 24 | 23 | 33–37 |
| Duplicate blocks | 0 | 0 | 0 |
| Day summary | yes | yes | no (per-section only) |
| Sub. cost / run | ~\$0.23 (5% weekly) | — | ~\$0.19 (4% weekly) |
| API cost / run | — | \$0.43 | — |
| Est. monthly (daily use) | ~\$7 | ~\$13 | ~\$6 |

**Map-reduce** produces the most compact output: the `reduce` step merges
overlapping blocks across map shards and the `split` step refines oversized
groups, resulting in fewer, denser blocks. Sections are well-separated
(e.g. global energy crisis vs. Croatian fuel response). Downside: 4× slower
and more expensive than oneshot due to the long `map` and `reduce` LLM calls.

**Oneshot** splits articles into shards processed in parallel, then merges
sections and removes duplicate blocks deterministically (exact duplicates by
article-ID set + subset absorption). Faster and cheaper, with per-section
summaries. Produces more blocks than map-reduce because cross-shard
consolidation is structural, not semantic — blocks that cover different
article sets but describe the same event are not merged.

**API mode** uses Haiku for most tasks and Sonnet only for reduce — faster and
cheaper per-token but adds up to ~\$13/month at daily use. CLI agents run under
the flat-rate subscription, where each run consumes 4–5% of the weekly quota.

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
