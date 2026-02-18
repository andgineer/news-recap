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

## Smoke-проверка и обновление моделей LLM-агентов

Быстрый smoke:

```bash
news-recap llm smoke
```

Матрица по профилям:

```bash
news-recap llm smoke --agent codex --model-profile fast
news-recap llm smoke --agent codex --model-profile quality
news-recap llm smoke --agent claude --model-profile fast
news-recap llm smoke --agent claude --model-profile quality
news-recap llm smoke --agent gemini --model-profile fast
news-recap llm smoke --agent gemini --model-profile quality
```

Для `llm enqueue-test` каждый `--source-id` должен принадлежать текущему user corpus и иметь
формат `article:<article_id>`; валидность `source_id` проверяется через `user_articles`.

Когда запускать автоматическое обновление mapping моделей:

- сразу при ошибке `model_not_available`;
- сразу, если smoke падает 2 раза подряд для одного `agent/profile`;
- после обновления CLI-агента (`codex --version`, `claude --version`, `gemini --version`);
- планово раз в неделю.

Когда **не** менять mapping моделей:

- `access_or_auth`;
- `billing_or_quota`.
- ошибки timeout на probe/runtime (`Probe timed out`, `Synthetic task timed out`).

В этих двух случаях сначала исправьте авторизацию или биллинг.

Примечание по Gemini:

- Для текущего CLI-потока `GEMINI_API_KEY` не нужен; используется авторизация Gemini CLI
  (преднастроенная сессия/login).

Готовый maintenance prompt для агента:

```text
You are the LLM model-maintenance agent for this repo.

Goal:
Validate current model routing for codex/claude/gemini and update model mappings only if needed.

Rules:
1) Work only in this repo.
2) Run smoke matrix for agents x profiles (fast, quality).
3) Treat auth/quota failures as non-model issues; do NOT change model mapping for them.
4) Change mapping only when failure indicates model drift (not found/deprecated/unsupported).
5) After each candidate change, re-run smoke for that exact agent/profile.
6) Keep edits minimal and deterministic.

Commands to use:
- news-recap llm smoke --agent codex --model-profile fast
- news-recap llm smoke --agent codex --model-profile quality
- news-recap llm smoke --agent claude --model-profile fast
- news-recap llm smoke --agent claude --model-profile quality
- news-recap llm smoke --agent gemini --model-profile fast
- news-recap llm smoke --agent gemini --model-profile quality

If a model drift is confirmed:
- Update env defaults/mapping in config.
- Update docs with new known-good defaults.
- Update tests that assert defaults.
- Run:
  - uv run pytest -q
  - source ./activate.sh && pre-commit run --verbose --all-files --

Output:
1) A short report with before/after matrix.
2) Exact files changed.
3) Unresolved blockers (if any).
```

Скрипт watchdog (рекомендуемая точка автоматизации):

```bash
scripts/model_watchdog.sh
scripts/model_watchdog.sh --run-refresh --refresh-agent codex
```

Коды выхода:

- `0` проверки успешны (или refresh выполнен успешно);
- `10` нужен refresh (есть триггеры, но `--run-refresh` не указан);
- `11` refresh запускался и завершился ошибкой;
- `12` обнаружены блокирующие auth/quota/timeout-ошибки.

## Очистка по retention

Удалить старые пользовательские связи со статьями по `discovered_at`:

```bash
news-recap ingest prune --days 30
```

Режим dry-run (без изменений в БД):

```bash
news-recap ingest prune --days 30 --dry-run
```

Автоочистка также запускается после `news-recap ingest daily`, если
`NEWS_RECAP_ARTICLE_RETENTION_DAYS > 0`.

Глобальный GC для shared-записей, на которые больше не ссылается ни один пользователь:

```bash
news-recap ingest gc
news-recap ingest gc --dry-run
```

Рекомендуемый порядок обслуживания:
1. Выполнить per-user очистку (`ingest prune`) для каждого пользовательского расписания.
2. Выполнить глобальный GC shared-данных (`ingest gc`).

## Полезные переменные окружения

- `NEWS_RECAP_DB_PATH`
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED`
- `NEWS_RECAP_RSS_FEED_ITEMS` (`<feed_url>|<items>,...`)
- `NEWS_RECAP_DEDUP_MODEL_NAME`
- `NEWS_RECAP_ARTICLE_RETENTION_DAYS`

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap ingest daily --help
news-recap ingest stats --help
news-recap ingest clusters --help
news-recap ingest duplicates --help
news-recap ingest prune --help
news-recap ingest gc --help
```
