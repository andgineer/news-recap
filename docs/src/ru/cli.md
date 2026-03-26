# CLI

`news-recap` управляется через CLI-команды, сгруппированные по этапам работы.

## Карта Команд

- `ingest`: импорт источников, статистика, проверка дедупа.
- `recap`: пайплайн ежедневного дайджеста (classify, enrich, deduplicate, map, reduce, split, group_sections, summarize).

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

Пайплайн проходит девять этапов: classify → load_resources → enrich →
deduplicate → map_blocks → reduce_blocks → split_blocks → group_sections →
summarize. Каждый этап чекпоинтится,
поэтому повторный запуск пропускает уже выполненные этапы.

```bash
news-recap recap run
news-recap recap run --api
news-recap recap run --date 2026-02-18
news-recap recap run --agent claude --stop-after classify
news-recap recap run --limit 50
```

Ключевые опции:
- `--data-dir`
- `--date` (бизнес-дата, по умолчанию — сегодня UTC)
- `--agent` (`codex`, `claude` или `gemini`)
- `--limit` (ограничить число загружаемых статей)
- `--api` (использовать прямой Anthropic API вместо CLI-агентов)
- `--fresh` (игнорировать незавершённый пайплайн и начать новый)
- `--oneshot` (заменить этапы map→reduce→split→group→summarize параллельными батчами
  по ~200 статей с последующим объединением секций через отдельный вызов LLM)
- `--use-api-key` (не удалять ключи API вендоров из окружения агента-подпроцесса;
  по умолчанию ключи удаляются, чтобы агент использовал лимиты подписки)
- `--stop-after` (`classify`, `load_resources`, `enrich`, `deduplicate`, `map_blocks`, `reduce_blocks`, `split_blocks`, `group_sections`, `summarize`)

## API-режим

По умолчанию recap-пайплайн выполняет LLM-задачи через запуск CLI-агентов
(`codex`, `claude`, `gemini`). **API-режим** заменяет вызовы подпроцессов прямыми
вызовами через Anthropic SDK — CLI-агенты не нужны.

> API-режим v1 поддерживает только Anthropic. Codex и Gemini работают только через CLI.

### Быстрый старт

```bash
export ANTHROPIC_API_KEY=sk-ant-...
news-recap recap run --api
```

Флаг `--api` автоматически задаёт `backend=api` и `agent=claude`. Других переменных окружения не требуется.

### Таблица моделей по задачам

По умолчанию быстрые задачи используют `claude-haiku-4-5-20251001`, а задача reduce —
`claude-sonnet-4-6`. Для переопределения отдельных задач используйте
`NEWS_RECAP_API_MODEL_MAP` (пары `task_type=model_id` через запятую):

```bash
export NEWS_RECAP_API_MODEL_MAP="recap_reduce=claude-sonnet-4-6,recap_summarize=claude-sonnet-4-6"
```

### Переменные окружения API-режима

- `NEWS_RECAP_EXECUTION_BACKEND` — `cli` (по умолчанию) или `api`.
- `NEWS_RECAP_API_MODEL_MAP` — переопределения модели по задачам (`task_type=model_id,...`).
- `NEWS_RECAP_API_MAX_PARALLEL` — начальный лимит параллелизма (по умолчанию `5`).
  Автоматически снижается при ошибках rate-limit и восстанавливается после успешных вызовов.
- `NEWS_RECAP_API_TIMEOUT_SECONDS` — таймаут одного вызова (по умолчанию `120`).
- `NEWS_RECAP_API_CONCURRENCY_RECOVERY_SUCCESSES` — число последовательных успехов
  для увеличения лимита параллелизма на 1 после снижения (по умолчанию `10`).
- `NEWS_RECAP_API_RETRY_MAX_BACKOFF_SECONDS` — потолок экспоненциальной задержки (по умолчанию `60`).
- `NEWS_RECAP_API_RETRY_JITTER_SECONDS` — равномерный джиттер для каждой задержки (по умолчанию `5`).
- `NEWS_RECAP_API_DOWNSHIFT_PAUSE_SECONDS` — дополнительная пауза после снижения лимита
  перед следующей попыткой захвата слота (по умолчанию `2`).

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

> **Подписка vs API-биллинг.** При запуске CLI-агентов (`claude`, `codex`, `gemini`)
> как подпроцессов `recap run` по умолчанию удаляет ключи API вендоров
> (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`)
> из окружения подпроцесса — чтобы агент использовал лимиты подписки, а не
> тарифицировал вызовы через API-аккаунт.
>
> В режиме `--api` ключ API нужен SDK и **не удаляется**. Флаг `--use-api-key` в этом
> режиме не влияет на работу.
>
> Чтобы явно передать ключ CLI-агенту (оплата за токены), используйте `--use-api-key`:
>
> ```bash
> news-recap recap run --use-api-key
> ```

- `NEWS_RECAP_LLM_DEFAULT_AGENT` — агент по умолчанию (`codex`, `claude` или `gemini`).
- `NEWS_RECAP_LLM_TASK_MODEL_MAP` — переопределения модели по типу задачи и агенту
  (`task_type:agent=model_flags,...`).

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap recap --help
```
