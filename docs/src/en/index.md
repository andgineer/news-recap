# news-recap

`news-recap` collects articles from RSS/Atom feeds and turns them into easy to read digest pages.

You can generate digest on schedule, for example at night.

The pipeline drives CLI agents such as ChatGPT Codex, Claude Code, and Antigravity CLI, so
it runs on flat-rate subscriptions.

Running it daily for 7 days consumes roughly 20% of the weekly Claude subscription
limit and about 10% for ChatGPT.

Alternatively it can run completely free with Antigravity CLI on the free tier.
With slightly less quality and from time to time hitting the limit so some days will be left without news recap.

For comparison, Inoreader charges an additional \$19.90/month **on top** of
a Pro subscription for AI-powered aggregation.

## Quick start

The free way needs no API keys: install [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
and the [Antigravity CLI](https://antigravity.google/) (`agy`, signed in with a Google account),
then install `news-recap`:

```bash
uv tool install news-recap --upgrade --python 3.13
```

Get an RSS URL. Inoreader example: open the context menu of the folder, choose `Properties`,
and copy the RSS link shown there.

Save it in your settings and create a digest:

```bash
news-recap config set rss "https://www.inoreader.com/stream/..."
news-recap ingest
news-recap create
news-recap serve
```

`news-recap config` shows your settings file (`~/.news_recap_data/config.toml`): language,
topics to exclude and follow, agent, feeds. To use a subscription agent instead of the free
one: `news-recap config set agent claude` (or `codex`).

Or set up scheduling (details in [Scheduled Runs](automation.md)):

```bash
news-recap schedule set
```

See [CLI](cli.md) for the full command reference.

## Optional: Jev {#optional-jev}

[TypeSafe Jev](https://docs.typesafe.ai/) can take over two yes/no decisions from the LLM: which
headlines to exclude or rewrite (`classify_backend`) and which articles are duplicates
(`dedup_backend`). It needs a paid API key (well under \$1 a month for classify, about
\$0.75 for dedup) and saves agent launches, which matters on the free Antigravity tier.

Put the key in `~/.news_recap_data/.env` (never in `config.toml`):

```bash
echo "TYPESAFE_API_KEY=..." >> ~/.news_recap_data/.env
news-recap config set classify_backend jev
news-recap config set dedup_backend jev
```

Jev reads exclude topics literally, so name what the stories are about ("celebrity gossip"),
not where they come from ("tabloids"). Without a key, both steps stay on the LLM.
