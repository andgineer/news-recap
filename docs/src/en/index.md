# news-recap

`news-recap` collects articles from RSS/Atom feeds and turns them into digest pages you
can review locally or generate on a schedule.

The pipeline drives CLI agents such as ChatGPT Codex, Claude Code, and Gemini CLI, so
it runs on flat-rate subscriptions.

Running it daily for 7 days consumes roughly 20% of the weekly Claude subscription
limit and less than that for ChatGPT / Google.

For comparison, Inoreader charges an additional \$19.90/month **on top** of
a Pro subscription for AI-powered aggregation.

## Quick start

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/), then install
`news-recap`:

```bash
uv tool install news-recap --upgrade --python 3.13
news-recap --help
```

Get an RSS URL.

Inoreader example: open the context menu of the folder, choose `Properties`,
and copy the RSS link shown there.

Run a digest manually:

```bash
news-recap ingest --rss "https://www.inoreader.com/stream/..."
news-recap create
news-recap serve
```

Or set up scheduling:

```bash
news-recap schedule set --rss "https://www.inoreader.com/stream/..."
```

See [Scheduled Runs](automation.md) for setup details, logs, and troubleshooting.
See [CLI](cli.md) for the full command reference.
