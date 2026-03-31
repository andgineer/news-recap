# Автозапуск

Сначала выполните шаги из `installation.md`.

Проверьте:

```bash
news-recap --help
```

Если планируете использовать Claude (агент по умолчанию для автозапуска), также проверьте:

```bash
claude
```

`claude` должен запускаться и уже быть авторизован.

## Установка

```bash
news-recap auto --rss https://your-feed.com/rss
```

Можно передать несколько фидов:

```bash
news-recap auto --rss https://feed1.com/rss --rss https://feed2.com/rss
```

Чтобы зафиксировать LLM-агента для шага recap:

```bash
news-recap auto --rss https://your-feed.com/rss --agent claude
```

Или задать переменную `NEWS_RECAP_RSS_FEED_URLS` (URL через запятую):

```bash
export NEWS_RECAP_RSS_FEED_URLS="https://feed1.com/rss,https://feed2.com/rss"
news-recap auto
```

Команда автоматически определит платформу и установит:

- **macOS**: LaunchAgent (`~/Library/LaunchAgents/com.news-recap.daily.plist`)
- **Linux**: systemd user timer (`~/.config/systemd/user/news-recap.timer`)
- **Windows**: Task Scheduler (`news-recap-daily`)

Повторный запуск безопасен — старая конфигурация заменяется.

## Проверка логов

macOS:

```bash
tail -f ~/Library/Logs/news-recap.log
```

Linux:

```bash
journalctl --user -u news-recap.service -n 200 --no-pager
```

Windows:

```powershell
Get-Content "$env:LOCALAPPDATA\news-recap\logs\news-recap.log" -Tail 200
```

## Удаление

```bash
news-recap auto-off
```

## Диагностика

Ошибки ниже относятся к `--agent claude`.

Если видите `Agent command not found: claude` — добейтесь, чтобы `claude`
запускался в обычном терминале, затем запустите `news-recap auto` ещё раз.

Если видите `Not logged in · Please run /login` — выполните `claude` и `/login`
в обычном терминале под тем же пользователем, затем запустите автозапуск вручную:

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
