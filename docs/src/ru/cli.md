# CLI

`news-recap` управляется через CLI-команды, сгруппированные по этапам работы.

## Карта Команд

- `ingest`: один цикл ingestion из RSS/Atom источников.
- `create`: создать дайджест новостей из последних статей.
- `prompt`: экспорт LLM-промпта из последних статей.
- `info`: показать важные пути приложения.
- `list`: показать завершённые дайджесты и непокрытые периоды.
- `delete`: удалить дайджест, чтобы его статьи стали доступны для следующего.
- `serve`: запуск веб-просмотрщика дайджестов.
- `config`: показать файл настроек (создаётся при первом вызове); `config set` меняет настройку.
- `schedule set`: установить или обновить ежедневный автозапуск.
- `schedule get`: показать текущую конфигурацию расписания.
- `schedule delete`: удалить ежедневный автозапуск.

## Общие Замечания

- Настройки хранятся в `config.toml` в каталоге данных; см. [`config`](#config).
- Каталог данных — `~/.news_recap_data`.
- Данные хранятся в JSON-файлах с ежедневным разбиением; старые партиции
  удаляются автоматически через `ingestion.retention_days` дней.

## Ingestion

### `ingest`
Один цикл ingestion из RSS/Atom источников.

```bash
news-recap ingest
news-recap ingest --rss https://example.com/feed.xml
```

Ключевые опции:
- `--rss` (повторяемая)

Если `--rss` не указан, фиды берутся из ключа `rss` в `config.toml`
(`news-recap config set rss URL [URL …]`).

## Команды пайплайна дайджеста

### `create`
Создать дайджест новостей из последних статей.

Пайплайн проходит следующие этапы: classify → load_resources → enrich → deduplicate → oneshot_digest (параллельные батчи + детерминистический дедуп блоков + объединение секций) → refine_layout (опциональная консолидация секций).

Каждый этап чекпоинтится, поэтому повторный запуск пропускает уже выполненные этапы.

```bash
news-recap create
news-recap create --api
news-recap create --agent claude --stop-after classify
news-recap create --limit 50
news-recap create --from-digest 3
```

Ключевые опции:
- `--agent` (`codex`, `claude` или `antigravity`)
- `--limit` (ограничить число загружаемых статей)
- `--max-days` (максимум дней для выборки статей; по умолчанию `ingestion.lookback_days`
  в `config.toml`, 2)
- `--all` (игнорировать предыдущие дайджесты; брать все статьи
  в пределах окна)
- `--api` (использовать прямой Anthropic API вместо CLI-агентов)
- `--fresh` (игнорировать незавершённый пайплайн и начать новый)
- `--from-digest N` (использовать статьи из существующего дайджеста по ID, как
  показано в `news-recap list`; бизнес-дата берётся из исходного дайджеста)
- `--use-api-key` (не удалять ключи API вендоров из окружения агента-подпроцесса;
  по умолчанию ключи удаляются, чтобы агент использовал лимиты подписки)
- `--stop-after` (`classify`, `load_resources`, `enrich`, `deduplicate`, `oneshot_digest`, `refine_layout`)

### `info`
Показать важные пути приложения: каталог данных, workdir, metadata расписания
и логи.

```bash
news-recap info
```

### `list`
Показать завершённые дайджесты с количеством статей, временным охватом и
непокрытыми периодами (промежутки между дайджестами).

```bash
news-recap list
```

Вывод — таблица (от новых к старым) с колонками: числовой ID (`#1` = самый
новый), бизнес-дата, число статей, временной период статей, время запуска
пайплайна, затраченное время, размер промптов, размер ответов и токены
(если доступны). ID можно использовать с `news-recap serve N` или
`news-recap delete N`.

Если между дайджестами есть временные промежутки не покрытые
статьями, они показываются в разделе «Uncovered periods».

Старые каталоги пайплайнов автоматически удаляются (тот же срок хранения,
что и у статей, `ingestion.retention_days` в `config.toml`).

### `delete`
Удалить дайджест, чтобы его статьи стали доступны для следующего.

```bash
news-recap delete 1
```

Аргументы:
- `DIGEST_ID` — ID дайджеста (как показано в `news-recap list`).

### `serve`
Запуск веб-просмотрщика для конкретного дайджеста.

```bash
news-recap serve
news-recap serve 2
```

Аргументы:
- `DIGEST_ID` (необязательный) — ID дайджеста (1 = самый новый, как показано
  в `news-recap list`). По умолчанию — последний завершённый дайджест.

Ключевые опции:
- `--host` — хост для привязки (по умолчанию `127.0.0.1`).
- `--port` — порт для привязки (по умолчанию `8080`).

### `config`
Показать настройки или изменить одну из них. Файл настроек — `config.toml` в каталоге данных
(`~/.news_recap_data/config.toml`); первый вызов `news-recap config` создаёт его со значениями
по умолчанию текущего релиза.

```bash
news-recap config                                   # путь к файлу и настройки
news-recap config set rss https://example.com/feed.xml https://example.org/rss
news-recap config set language en
news-recap config set agent claude                  # antigravity | codex | claude
news-recap config set exclude "horoscopes" "sports (except Russia)"
news-recap config set classify_backend jev          # llm | jev
```

`config set` меняет ключи `language`, `exclude`, `follow`, `agent`, `rss`, `classify_backend`,
`dedup_backend`. `exclude` и `follow` принимают по одной теме на аргумент и хранятся по одной
на строку; пояснение в скобках — исключение («sports (except Russia)»). Комментарии и всё
остальное в файле сохраняются.

Остальное в `config.toml` — расширенные настройки, записанные закомментированными со
значением по умолчанию текущего релиза: приложение следует умолчаниям каждого нового релиза,
пока вы не раскомментируете строку. См. [справочник настроек](#config-toml).

Приоритет (от высшего к низшему): флаги CLI (`--rss`, `--agent`, `--language`), затем
`config.toml`, затем значения по умолчанию релиза.

## API-режим

По умолчанию пайплайн дайджеста выполняет LLM-задачи через запуск CLI-агентов
(`codex`, `claude`, `antigravity`). **API-режим** заменяет вызовы подпроцессов прямыми
вызовами через Anthropic SDK — CLI-агенты не нужны.

> API-режим v1 поддерживает только Anthropic. Codex и Antigravity работают только через CLI.

### Быстрый старт

```bash
export ANTHROPIC_API_KEY=sk-ant-...
news-recap create --api
```

Флаг `--api` включает API-режим и агента `claude` для этого запуска.

### Таблица моделей по задачам

По умолчанию экономичные этапы используют `claude-haiku-4-5-20251001`, а
`recap_merge_sections` — `claude-sonnet-5`. Отдельные задачи переопределяются в секции `[api]`
файла `config.toml`:

```toml
[api]
model_map.recap_merge_sections = "claude-sonnet-5"
```

### Настройки API-режима {#api-settings}

В секции `[api]` файла `config.toml`:

- `max_parallel` — начальный лимит параллелизма (по умолчанию `5`). Автоматически снижается
  при ошибках rate-limit и восстанавливается после успешных вызовов.
- `concurrency_recovery_successes` — число последовательных успехов для увеличения лимита на 1
  после снижения (по умолчанию `10`).
- `retry_max_backoff_seconds` — потолок экспоненциальной задержки (по умолчанию `60`).
- `retry_jitter_seconds` — равномерный джиттер для каждой задержки (по умолчанию `5`).
- `downshift_pause_seconds` — дополнительная пауза после снижения лимита перед следующей
  попыткой захвата слота (по умолчанию `2`).

`llm.execution_backend = "api"` (вместе с `agent = "claude"`) делает API-режим режимом по
умолчанию.

## Автозапуск

Подробная настройка, платформенные детали, логи и диагностика: [Запуск по расписанию](automation.md).

## Справочник настроек (config.toml) {#config-toml}

Основные ключи (их же меняет `news-recap config set`):

- `language` — язык дайджеста, код BCP-47 (`en`, `ru`, `sr`, …). По умолчанию `ru`.
- `exclude` — исключаемые темы, по одной на строку. Называйте, о чём новости («celebrity
  gossip»), а не откуда они («tabloids»): Jev читает темы буквально.
- `follow` — темы, получающие собственные разделы, по одной на строку.
- `agent` — `antigravity` (бесплатный тариф Gemini, без ключей; по умолчанию), `codex` или
  `claude`.
- `rss` — URL фидов.
- `classify_backend`, `dedup_backend` — `llm` (по умолчанию) или `jev`; см.
  [Jev](index.md#jev).

Расширенные секции, записанные закомментированными со значениями по умолчанию:

- `[ingestion]` — `lookback_days` (максимум дней статей в дайджесте, по умолчанию 2; окно
  начинается от последнего дайджеста, `--all` берёт всё окно), `retention_days` (сколько дней
  хранить партиции статей, по умолчанию 7), `page_size`, `max_pages`, `backfill_max_gaps`,
  `clean_text_max_chars`, `min_resource_chars`.
- `[fetch]` — загрузка RSS: `default_items_per_feed`, `per_feed_items`
  (`{ "https://…" = 500 }`), `snapshot_max_age_hours`, `max_retries`, `retry_backoff_seconds`,
  `request_timeout_seconds`.
- `[dedup]` — `threshold` (порог эмбеддингового сходства группы-кандидата, по умолчанию 0.9),
  `model_name`.
- `[llm]` — `workdir_root`, `execution_backend` (`cli` | `api`) и флаги модели по задаче и
  агенту: `models.recap_classify.claude = "--model haiku"`.
- `[api]` — см. [Настройки API-режима](#api-settings).

Переменные окружения — только для секретов:

- `TYPESAFE_API_KEY` — ключ Jev; читается также из `.env` в текущем каталоге или в каталоге
  данных.
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTIGRAVITY_API_KEY` — ключи API агентов (см. ниже).

> **Подписка vs API-биллинг.** При запуске CLI-агентов (`claude`, `codex`, `antigravity`)
> как подпроцессов `news-recap create` по умолчанию удаляет ключи API вендоров
> (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTIGRAVITY_API_KEY`)
> из окружения подпроцесса — чтобы агент использовал лимиты подписки, а не
> тарифицировал вызовы через API-аккаунт.
>
> В режиме `--api` ключ API нужен SDK и **не удаляется**. Флаг `--use-api-key` в этом
> режиме не влияет на работу.
>
> Чтобы явно передать ключ CLI-агенту (оплата за токены), используйте `--use-api-key`:
>
> ```bash
> news-recap create --use-api-key
> ```

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap create --help
news-recap prompt --help
news-recap info --help
news-recap list --help
news-recap delete --help
news-recap serve --help
news-recap config --help
news-recap schedule --help
news-recap schedule set --help
```
