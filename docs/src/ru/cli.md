# CLI

`news-recap` управляется через CLI-команды, сгруппированные по этапам работы.

## Карта Команд

- `ingest`: импорт источников, статистика, проверка дедупа.
- `recap`: пайплайн ежедневного дайджеста (classify, enrich, group, synthesize, compose).

## Общие Замечания

- Большинство команд поддерживают `--data-dir` для выбора каталога данных.
- Данные хранятся в JSON-файлах с ежедневным разбиением; старые партиции
  удаляются автоматически по значению `NEWS_RECAP_GC_RETENTION_DAYS`.

## Команды Ingestion

### `ingest daily`
Один цикл ingestion из RSS/Atom источников.

```bash
news-recap ingest daily
news-recap ingest daily --feed-url https://example.com/feed.xml
```

Ключевые опции:
- `--feed-url` (повторяемая)
- `--data-dir`

Если `--feed-url` не указан, фиды берутся из:
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_FEED_URL`

### `ingest stats`
Статистика ingestion и дедупа в заданном окне времени.

```bash
news-recap ingest stats --hours 24 --recent-runs 5
```

Ключевые опции:
- `--hours`
- `--source`
- `--recent-runs`

### `ingest clusters`
Распределение dedup-кластеров по запуску.

```bash
news-recap ingest clusters --hours 24 --limit 20
news-recap ingest clusters --run-id <run_id> --show-members
```

Ключевые опции:
- `--run-id` или `--hours`/`--source` для выбора запуска
- `--min-size`
- `--members-per-cluster`
- `--show-members`

### `ingest duplicates`
Примеры дублей (кластеры размером >= 2).

```bash
news-recap ingest duplicates --hours 24 --limit-clusters 10
```

Ключевые опции:
- `--run-id` или `--hours`/`--source`
- `--limit-clusters`
- `--members-per-cluster`

## Команды Recap-пайплайна

### `recap run`
Запуск полного пайплайна дайджеста на бизнес-дату.

Пайплайн проходит шесть этапов: classify → enrich → group →
deep-enrich → synthesize → compose. Каждый этап чекпоинтится,
поэтому повторный запуск пропускает уже выполненные этапы.

```bash
news-recap recap run
news-recap recap run --date 2026-02-18
news-recap recap run --agent claude --stop-after classify
news-recap recap run --limit 50
```

Ключевые опции:
- `--data-dir`
- `--date` (бизнес-дата, по умолчанию — сегодня UTC)
- `--agent` (`codex`, `claude` или `gemini`)
- `--limit` (ограничить число загружаемых статей)
- `--stop-after` (`classify`, `enrich`, `group`, `enrich_full`, `synthesize`, `compose`)

## Важные Переменные Окружения

### Данные и хранение
- `NEWS_RECAP_DATA_DIR` — корневой каталог для всех файлов данных.
- `NEWS_RECAP_GC_RETENTION_DAYS` — сколько дней хранить партиции статей (по умолчанию 7).
- `NEWS_RECAP_DIGEST_LOOKBACK_DAYS` — за сколько дней брать статьи для дайджеста (по умолчанию 3).

### RSS-фиды
- `NEWS_RECAP_RSS_FEED_URLS` — список URL фидов через запятую.
- `NEWS_RECAP_RSS_FEED_URL` — один URL фида (для удобства).
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED` — максимум элементов на фид.
- `NEWS_RECAP_RSS_FEED_ITEMS` — переопределения числа элементов по фидам (`<feed_url>|<items>,...`).

### LLM-агенты

> **Подписка vs API-биллинг.** CLI-агенты (`claude`, `codex`, `gemini`) сначала
> проверяют наличие API-ключа вендора. Если ключ задан, использование тарифицируется
> через API-аккаунт (оплата за токены). Чтобы использовать лимиты подписки, сбросьте ключ:
>
> ```bash
> unset ANTHROPIC_API_KEY   # Claude — использовать подписку Claude Pro/Max
> unset OPENAI_API_KEY      # Codex — использовать подписку ChatGPT/Codex
> unset GEMINI_API_KEY      # Gemini — использовать подписку Google AI
> ```

- `NEWS_RECAP_LLM_DEFAULT_AGENT` — агент по умолчанию (`codex`, `claude` или `gemini`).
- `NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP` — профиль модели по типу задачи (`fast`/`quality`).
- `NEWS_RECAP_CODEX_COMMAND_TEMPLATE` — шаблон команды для Codex.
- `NEWS_RECAP_CLAUDE_COMMAND_TEMPLATE` — шаблон команды для Claude.
- `NEWS_RECAP_GEMINI_COMMAND_TEMPLATE` — шаблон команды для Gemini.
- `NEWS_RECAP_LLM_CODEX_MODEL_FAST` / `NEWS_RECAP_LLM_CODEX_MODEL_QUALITY`
- `NEWS_RECAP_LLM_CLAUDE_MODEL_FAST` / `NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY`
- `NEWS_RECAP_LLM_GEMINI_MODEL_FAST` / `NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY`

### Prefect
- `NEWS_RECAP_PREFECT_MODE` — `ephemeral` (по умолчанию), `server` или `auto`.
- `PREFECT_API_URL` — URL Prefect-сервера (обязателен в режиме `server`).

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap recap --help
```
