# news-recap

`news-recap` collects articles from RSS/Atom feeds and turns them into digest pages you
can review locally or generate on a schedule.

## Quick start

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/), then install
`news-recap`:

```bash
uv tool install news-recap
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
