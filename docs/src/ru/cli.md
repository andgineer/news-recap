# CLI (текущий MVP)

В Epic 1 продукт работает через CLI-команды.

## Основная команда

Один цикл ingestion:

```bash
news-recap ingest daily
```

Часто используемые опции:

- `--db-path PATH` — путь к SQLite-файлу.
- `--feed-url TEXT` — URL RSS/Atom фида (можно указывать несколько раз).

Если `--feed-url` не передан, фиды берутся из:

- `NEWS_RECAP_RSS_FEED_URLS` (через запятую),
- при необходимости `NEWS_RECAP_RSS_FEED_URL`.

## Как получить RSS-ссылку в Inoreader

1. В Inoreader откройте нужную папку или тэг (label), который хотите читать.
2. Откройте меню этой папки/тэга и найдите пункт публикации RSS
   (`Create output feed`, `Output RSS` или похожее название).
3. Создайте output feed и скопируйте выданную ссылку вида
   `https://www.inoreader.com/stream/user/...`.
4. Передайте ссылку приложению:

```bash
export NEWS_RECAP_RSS_FEED_URLS="https://www.inoreader.com/stream/user/..."
news-recap ingest daily
```

Важно:
- Ссылка output feed обычно персональная. Не публикуйте ее в открытом доступе.
- Не нужно вручную добавлять `?n=...` в URL. Приложение само добавляет лимит элементов
  через `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED` (по умолчанию `10000`) или
  через `NEWS_RECAP_RSS_FEED_ITEMS` для конкретных фидов.

## Команды наблюдаемости

Статистика запусков и дедупликации:

```bash
news-recap ingest stats --hours 24
```

Просмотр кластеров:

```bash
news-recap ingest clusters --hours 24 --limit 20
news-recap ingest clusters --run-id <run_id> --show-members
```

Просмотр примеров дублей:

```bash
news-recap ingest duplicates --hours 24 --limit-clusters 10
news-recap ingest duplicates --run-id <run_id>
```

## Полезные переменные окружения

- `NEWS_RECAP_DB_PATH`
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED`
- `NEWS_RECAP_RSS_FEED_ITEMS` (`<feed_url>|<items>,...`)
- `NEWS_RECAP_DEDUP_MODEL_NAME`

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap ingest daily --help
news-recap ingest stats --help
news-recap ingest clusters --help
news-recap ingest duplicates --help
```
