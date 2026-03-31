# news-recap

`news-recap` собирает статьи из RSS/Atom и превращает их в дайджесты, которые можно
собрать вручную, посмотреть локально или запускать по расписанию.

## Быстрый старт

Установите [`uv`](https://docs.astral.sh/uv/getting-started/installation/), затем
установите `news-recap`:

```bash
uv tool install news-recap
news-recap --help
```

Получите RSS-ссылку.

Пример для Inoreader: откройте контекстное меню папки, выберите `Properties` и
скопируйте RSS-ссылку оттуда.

Запустите дайджест вручную:

```bash
news-recap ingest --rss "https://www.inoreader.com/stream/..."
news-recap create
news-recap serve
```

Или настройте расписание:

```bash
news-recap schedule set --rss "https://www.inoreader.com/stream/..."
```

Подробности по настройке, логам и диагностике: [Автозапуск](automation.md).
Полный список команд: [CLI](cli.md).
