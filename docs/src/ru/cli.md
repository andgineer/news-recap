# CLI

`news-recap` управляется через CLI-команды, сгруппированные по этапам работы.

## Карта Команд

- `ingest`: импорт источников, статистика, проверка дедупа, очистка retention.
- `llm`: очередь задач, worker, ретраи, smoke-проверки, benchmark.
- `stories`: pinned-сюжеты и построение дневных назначений.
- `highlights`: постановка генерации highlights.
- `story-details`: постановка детальной генерации по одному сюжету.
- `monitors`: создание/список/запуск monitor-промптов.
- `qa`: ad-hoc вопросы в очередь.
- `read-state`: отметки чтения/открытия output/блоков.
- `feedback`: like/dislike/hide/pin для output/блоков.
- `insights`: доменная статистика и список сохраненных output.

## Общие Замечания

- Большинство команд поддерживают `--db-path` для выбора SQLite-файла.
- `source_id` должен иметь формат `article:<article_id>`.
- Задачи очереди исполняются командой `news-recap llm worker`.

## Команды Ingestion

### `ingest daily`
Один цикл ingestion из RSS/Atom источников.

```bash
news-recap ingest daily
news-recap ingest daily --feed-url https://example.com/feed.xml
```

Ключевые опции:
- `--feed-url` (повторяемая)
- `--db-path`

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

### `ingest prune`
Удаление старых user-article связей по `discovered_at`.

```bash
news-recap ingest prune --days 30
news-recap ingest prune --days 30 --dry-run
```

Ключевые опции:
- `--days`
- `--dry-run/--no-dry-run`

### `ingest gc`
Удаление глобально неиспользуемых shared-записей.

```bash
news-recap ingest gc
news-recap ingest gc --dry-run
```

Ключевые опции:
- `--dry-run/--no-dry-run`

## Команды LLM-Очереди

### `llm enqueue-test`
Постановка тестовой задачи в очередь с optional routing overrides.

```bash
news-recap llm enqueue-test --task-type highlights --prompt "Top updates"
```

Ключевые опции:
- `--task-type`
- `--prompt`
- `--source-id` (повторяемая)
- `--priority`
- `--agent`, `--model-profile`, `--model`
- `--max-attempts`, `--timeout-seconds`

### `llm worker`
Запуск worker в режиме `--once` или `--loop`.

```bash
news-recap llm worker --once
news-recap llm worker --loop --max-tasks 100
```

### `llm stats`
Статистика очереди, валидации/ретраев и latency.

```bash
news-recap llm stats --hours 24
```

### `llm benchmark`
Детерминированный benchmark очереди с отчетом.

```bash
news-recap llm benchmark --tasks-per-type 10
news-recap llm benchmark --task-type highlights --task-type qa --use-configured-agent
```

Ключевые опции:
- `--task-type` (повторяемая)
- `--tasks-per-type`
- `--source-id` (повторяемая)
- `--output`
- `--use-benchmark-agent/--use-configured-agent`

### `llm tasks`
Список задач очереди (с фильтром по статусу).

```bash
news-recap llm tasks --status queued --limit 50
```

### `llm inspect`
Подробный просмотр одной задачи с event timeline.

```bash
news-recap llm inspect --task-id <task_id>
```

### `llm retry`
Ручной retry для `failed/timeout/canceled`.

```bash
news-recap llm retry --task-id <task_id>
```

### `llm cancel`
Отмена `queued/running` задачи.

```bash
news-recap llm cancel --task-id <task_id>
```

### `llm smoke`
Прямые smoke-проверки CLI-агентов без DB-очереди.

```bash
news-recap llm smoke
news-recap llm smoke --agent codex --model-profile quality
news-recap llm smoke --agent gemini --model gemini-2.5-flash
```

Ключевые опции:
- `--agent` (повторяемая)
- `--model-profile` (`fast`/`quality`)
- `--model`
- `--prompt`, `--expect-substring`, `--timeout-seconds`
- `--claude-command`, `--codex-command`, `--gemini-command`

## Команды Сюжетов и Генерации

### `stories define`
Создать или обновить pinned-сюжет.

```bash
news-recap stories define --name "Serbia updates" --description "Politics and economy" --target-language sr
```

Ключевые опции:
- `--story-id` (для update)
- `--name`
- `--description`
- `--target-language`
- `--priority`
- `--enabled/--disabled`

### `stories list`
Список pinned-сюжетов.

```bash
news-recap stories list
news-recap stories list --all
```

### `stories build`
Построение pinned + auto назначений на дату.

```bash
news-recap stories build
news-recap stories build --date 2026-02-18
```

### `highlights generate`
Поставить в очередь генерацию highlights на дату.

```bash
news-recap highlights generate --date 2026-02-18
```

Ключевые опции:
- `--date`
- `--priority`
- `--agent`, `--model-profile`, `--model`
- `--max-attempts`, `--timeout-seconds`

### `story-details generate`
Поставить в очередь детальную генерацию по pinned-сюжету.

```bash
news-recap story-details generate --story-id <story_id> --date 2026-02-18
```

Ключевые опции:
- `--story-id`
- `--date`
- routing/attempt/timeout опции (как у highlights)

## Команды Monitors и Q&A

### `monitors define`
Создать или обновить monitor-промпт.

```bash
news-recap monitors define --name "Macro risks" --prompt "What changed in macro risk today?"
```

Ключевые опции:
- `--monitor-id` (для update)
- `--name`
- `--prompt`
- `--cadence`
- `--enabled/--disabled`

### `monitors list`
Список monitor-определений.

```bash
news-recap monitors list
news-recap monitors list --all
```

### `monitors run`
Поставить в очередь задачи monitor answer для enabled monitors.

```bash
news-recap monitors run --date 2026-02-18
```

Ключевые опции:
- `--date`
- routing/attempt/timeout опции

### `qa ask`
Поставить в очередь ad-hoc Q&A с bounded retrieval.

```bash
news-recap qa ask --prompt "What were the top geopolitical updates today?"
news-recap qa ask --prompt "What changed in energy markets?" --lookback-days 7
```

Ключевые опции:
- `--prompt`
- `--lookback-days`
- routing/attempt/timeout опции

## Команды Read-state и Feedback

### `read-state mark`
Записать событие чтения/открытия для output или блока.

```bash
news-recap read-state mark --output-id <output_id> --event-type open
news-recap read-state mark --output-id <output_id> --event-type view --output-block-id 3
```

### `feedback add`
Добавить feedback к output или отдельному блоку.

```bash
news-recap feedback add --output-id <output_id> --feedback-type like
news-recap feedback add --output-id <output_id> --feedback-type hide --output-block-id 2
```

## Команды Insights

### `insights stats`
Доменные счетчики по stories/outputs/engagement.

```bash
news-recap insights stats --hours 24
```

### `insights outputs`
Список сохраненных бизнес-output.

```bash
news-recap insights outputs --limit 20
news-recap insights outputs --kind highlights --date 2026-02-18
```

## Важные Переменные Окружения

- `NEWS_RECAP_DB_PATH`
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED`
- `NEWS_RECAP_RSS_FEED_ITEMS` (`<feed_url>|<items>,...`)
- `NEWS_RECAP_ARTICLE_RETENTION_DAYS`
- `NEWS_RECAP_LLM_DEFAULT_AGENT`
- `NEWS_RECAP_LLM_TASK_TYPE_PROFILE_MAP`
- `NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_CLAUDE_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE`
- `NEWS_RECAP_LLM_CODEX_MODEL_FAST` / `NEWS_RECAP_LLM_CODEX_MODEL_QUALITY`
- `NEWS_RECAP_LLM_CLAUDE_MODEL_FAST` / `NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY`
- `NEWS_RECAP_LLM_GEMINI_MODEL_FAST` / `NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY`
- `NEWS_RECAP_QA_LOOKBACK_DAYS`
- `NEWS_RECAP_RETRIEVAL_TOP_K`
- `NEWS_RECAP_RETRIEVAL_MAX_ARTICLES`
- `NEWS_RECAP_RETRIEVAL_TOKEN_BUDGET`
- `NEWS_RECAP_RETRIEVAL_CHAR_BUDGET`

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap llm --help
news-recap stories --help
news-recap highlights --help
news-recap story-details --help
news-recap monitors --help
news-recap qa --help
news-recap read-state --help
news-recap feedback --help
news-recap insights --help
```
