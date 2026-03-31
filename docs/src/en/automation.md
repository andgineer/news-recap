# Automation

Complete the steps in `installation.md` first.

Verify:

```bash
news-recap --help
```

If you plan to use Claude as the agent (the default for automation), also check:

```bash
claude
```

`claude` must launch and already be logged in.

## Setup

```bash
news-recap schedule set --rss https://your-feed.com/rss
```

Multiple feeds:

```bash
news-recap schedule set --rss https://feed1.com/rss --rss https://feed2.com/rss
```

To pin a specific LLM agent for the digest step:

```bash
news-recap schedule set --rss https://your-feed.com/rss --agent claude
```

To change the daily run time (default 03:00):

```bash
news-recap schedule set --rss https://your-feed.com/rss --time 07:30
```

To use the current Python venv instead of global `news-recap`:

```bash
news-recap schedule set --rss https://your-feed.com/rss --venv
```

Or set `NEWS_RECAP_RSS_FEED_URLS` (comma-separated):

```bash
export NEWS_RECAP_RSS_FEED_URLS="https://feed1.com/rss,https://feed2.com/rss"
news-recap schedule set
```

The command auto-detects the platform and installs:

- **macOS**: LaunchAgent (`~/Library/LaunchAgents/com.news-recap.daily.plist`)
- **Linux**: systemd user timer (`~/.config/systemd/user/news-recap.timer`)
- **Windows**: Task Scheduler (`news-recap-daily`)

Re-running is safe — the previous configuration is replaced.

## Checking the schedule

```bash
news-recap schedule get
```

## Checking logs

macOS:

```bash
tail -f ~/Library/Logs/news-recap/news-recap-$(date +%Y-%m-%d).log
```

Linux:

```bash
journalctl --user -u news-recap.service -n 200 --no-pager
```

Windows:

```powershell
Get-Content "$env:LOCALAPPDATA\news-recap\logs\news-recap-$(Get-Date -Format 'yyyy-MM-dd').log" -Tail 200
```

## Removal

```bash
news-recap schedule delete
```

## Troubleshooting

The errors below apply when using `--agent claude`.

If you see `Agent command not found: claude` — make sure `claude` runs
in your regular terminal, then run `news-recap schedule set` again.

If you see `Not logged in · Please run /login` — run `claude` and `/login`
in your regular terminal under the same user, then trigger the job manually:

macOS:

```bash
launchctl start com.news-recap.daily
```

Linux:

```bash
systemctl --user start news-recap.service
```

Windows:

```powershell
Start-ScheduledTask -TaskName "news-recap-daily"
```
