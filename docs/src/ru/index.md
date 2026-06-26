# news-recap

`news-recap` собирает статьи из RSS/Atom и превращает их в удобные для чтения дайджесты.

Создание дайджестов запускать по расписанию, ночью.

Использует CLI-агенты — ChatGPT Codex, Claude Code, Antigravity CLI — и работает
в рамках подписок с фиксированной ценой.

При ежедневном использовании за 7 дней расходуется примерно 20% недельного лимита
подписки Claude, для ChatGPT — ещё меньше.

На Free-tier Antigravity CLI он работает вообще бесплатно, хотя и чуть с меньшим качеством.

Для сравнения, Inoreader за ИИ-агрегацию берёт дополнительно \$19.90/мес **сверх**
Pro-подписки.

## Быстрый старт

Установите [`uv`](https://docs.astral.sh/uv/getting-started/installation/), затем
установите `news-recap`:

```bash
uv tool install news-recap --upgrade --python 3.13
news-recap --help
```

Получите RSS-ссылку.

Пример для Inoreader: откройте контекстное меню папки, выберите `Properties` и
скопируйте RSS-ссылку оттуда.

Создайте дайджест вручную:

```bash
news-recap ingest --rss "https://www.inoreader.com/stream/..."
news-recap create
```

Или настройте расписание (подробнее в [Запуск по расписанию](automation.md)):

```bash
news-recap schedule set --rss "https://www.inoreader.com/stream/..."
```

Читайте:

```bash
news-recap serve
```

Полный список команд: [CLI](cli.md).
