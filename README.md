[![Build Status](https://github.com/andgineer/news-recap/workflows/CI/badge.svg)](https://github.com/andgineer/news-recap/actions)
[![Coverage](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)
# news-recap

**Your feeds. Fewer repeats. A clearer picture.**

Turn RSS feeds into a daily digest: related reports grouped together, vague
headlines clarified, and links back to the original sources. Choose the topics
to follow, the noise to exclude, and the language to read in.

* **Read stories, not a wall of headlines.** Related reports come together in
  topic sections, with summaries and links to their sources.
* **Get past the clickbait.** When a headline hides the news, the pipeline fetches
  the article and rewrites the headline from its content.
* **Have it ready when you are.** Schedule digest creation and read it in the
  browser. Interrupted runs resume from saved progress.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and set up
one of the supported [CLI agents](spec/agents.md), then run:

```bash
uv tool install news-recap --upgrade --python 3.13
news-recap ingest --rss "YOUR_RSS_URL"
news-recap create --agent codex
news-recap serve
```

Use `--agent claude` or `--agent antigravity` to choose another backend.
For scheduled runs, feed setup, and preferences, see the
[manual](https://andgineer.github.io/news-recap/).

## Under the hood

**Storage that fits the workflow.** I started with SQLite, SQLModel, and Alembic,
then found that the database added more machinery than this batch-processing
workflow needed. Typed `msgspec` structures now carry data through processing
and JSON storage, with daily article partitions and resumable checkpoints.
The [database prototype](https://github.com/andgineer/news-recap/tree/sql-poc)
remains available for comparison.

**Spend model calls where judgment matters.** Embeddings narrow down candidate
duplicates; LLMs decide which reports belong together and write the digest.
Code removes duplicate and overlapping blocks after generation. Full articles
are fetched selectively, when their headlines need clarification.

**Coding agents as pipeline workers.** The pipeline invokes Codex, Claude Code,
or Antigravity through their CLI interfaces, with task-specific model selection
and saved intermediate results. The [agent integration guide](spec/agents.md)
describes the launch commands and task contracts for adapting this approach to
another batch-processing application.

### Development process

In this project, I experimented with an iterative development workflow using
Codex and Claude Code: written plans, implementation, and separate review passes,
followed by trials on real news feeds.

Those trials also shaped the architecture. The
[pipeline experiments](spec/pipeline.md#experiments) compare digest strategies
on the same article corpus, including processing time, article coverage, and
the resulting section structure.

<details>
<summary><b>Contributing</b></summary>

Bootstrap the development environment and install pre-commit hooks:

```bash
source ./activate.sh
pre-commit install
```

Run the checks and test suite:

```bash
uv run inv pre
uv run pytest --cov=src tests/
```

See the [contributor guide](AGENTS.md) for repository conventions and
`uv run invoke --list` for available development tasks.

[Allure test report](https://andgineer.github.io/news-recap/builds/tests/)

</details>
