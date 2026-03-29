# CLI

`news-recap` управляется через CLI-команды, сгруппированные по этапам работы.

## Карта Команд

- `ingest`: один цикл ingestion из RSS/Atom источников.
- `recap`: запуск пайплайна ежедневного дайджеста.
- `prompt`: экспорт LLM-промпта из последних статей.
- `list`: показать завершённые дайджесты и непокрытые периоды.
- `serve`: запуск веб-просмотрщика дайджестов.

## Общие Замечания

- Каталог данных задаётся переменной `NEWS_RECAP_DATA_DIR` (по умолчанию `.news_recap_data`).
- Данные хранятся в JSON-файлах с ежедневным разбиением; старые партиции
  удаляются автоматически по значению `NEWS_RECAP_GC_RETENTION_DAYS`.

## Ingestion

### `ingest`
Один цикл ingestion из RSS/Atom источников.

```bash
news-recap ingest
news-recap ingest --feed-url https://example.com/feed.xml
```

Ключевые опции:
- `--feed-url` (повторяемая)

Если `--feed-url` не указан, фиды берутся из:
- `NEWS_RECAP_RSS_FEED_URLS`
- `NEWS_RECAP_RSS_FEED_URL`

## Команды пайплайна дайджеста

### `recap`
Запуск полного пайплайна дайджеста на бизнес-дату.

Пайплайн проходит следующие этапы: classify → load_resources → enrich → deduplicate → oneshot_digest (параллельные батчи + детерминистический дедуп блоков + объединение секций) → refine_layout (опциональная консолидация секций).

Каждый этап чекпоинтится, поэтому повторный запуск пропускает уже выполненные этапы.

```bash
news-recap recap
news-recap recap --api
news-recap recap --agent claude --stop-after classify
news-recap recap --limit 50
news-recap recap --from-pipeline .news_recap_workdir/pipeline-2026-03-25-105004
```

Ключевые опции:
- `--agent` (`codex`, `claude` или `gemini`)
- `--limit` (ограничить число загружаемых статей)
- `--max-days` (максимум дней для выборки статей; по умолчанию 2,
  переменная `NEWS_RECAP_DIGEST_LOOKBACK_DAYS`)
- `--all` (игнорировать предыдущие дайджесты; брать все статьи
  в пределах окна)
- `--api` (использовать прямой Anthropic API вместо CLI-агентов)
- `--fresh` (игнорировать незавершённый пайплайн и начать новый)
- `--from-pipeline` (использовать статьи из предыдущего пайплайна; бизнес-дата
  берётся из исходного пайплайна)
- `--use-api-key` (не удалять ключи API вендоров из окружения агента-подпроцесса;
  по умолчанию ключи удаляются, чтобы агент использовал лимиты подписки)
- `--stop-after` (`classify`, `load_resources`, `enrich`, `deduplicate`, `oneshot_digest`, `refine_layout`)

### `list`
Показать завершённые дайджесты с количеством статей, временным охватом и
непокрытыми периодами (промежутки между дайджестами).

```bash
news-recap list
```

Вывод содержит список завершённых дайджестов (от новых к старым): числовой ID
(`#1` = самый новый), бизнес-дату, число статей, самую раннюю/позднюю дату
публикации статей и имя каталога пайплайна. ID можно использовать с
`news-recap serve N`.

Если между дайджестами есть временные промежутки не покрытые
статьями, они показываются в разделе «Uncovered periods».

Старые каталоги пайплайнов автоматически удаляются (тот же срок хранения,
что и у статей, управляется `NEWS_RECAP_GC_RETENTION_DAYS`).

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

## API-режим

По умолчанию recap-пайплайн выполняет LLM-задачи через запуск CLI-агентов
(`codex`, `claude`, `gemini`). **API-режим** заменяет вызовы подпроцессов прямыми
вызовами через Anthropic SDK — CLI-агенты не нужны.

> API-режим v1 поддерживает только Anthropic. Codex и Gemini работают только через CLI.

### Быстрый старт

```bash
export ANTHROPIC_API_KEY=sk-ant-...
news-recap recap --api
```

Флаг `--api` автоматически задаёт `backend=api` и `agent=claude`. Других переменных окружения не требуется.

### Таблица моделей по задачам

По умолчанию все задачи используют `claude-haiku-4-5-20251001`. Для переопределения
отдельных задач используйте `NEWS_RECAP_API_MODEL_MAP` (пары `task_type=model_id`
через запятую):

```bash
export NEWS_RECAP_API_MODEL_MAP="recap_oneshot_digest=claude-sonnet-4-6,recap_classify=claude-haiku-4-5-20251001"
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
- `NEWS_RECAP_DIGEST_LOOKBACK_DAYS` — максимум дней для выборки статей в дайджест (по умолчанию 2).
  По умолчанию окно начинается от даты последнего успешного дайджеста;
  `--all` отключает эту привязку.

### RSS-фиды
- `NEWS_RECAP_RSS_FEED_URLS` — список URL фидов через запятую.
- `NEWS_RECAP_RSS_FEED_URL` — один URL фида (для удобства).
- `NEWS_RECAP_RSS_DEFAULT_ITEMS_PER_FEED` — максимум элементов на фид.
- `NEWS_RECAP_RSS_FEED_ITEMS` — переопределения числа элементов по фидам (`<feed_url>|<items>,...`).

### LLM-агенты

> **Подписка vs API-биллинг.** При запуске CLI-агентов (`claude`, `codex`, `gemini`)
> как подпроцессов `news-recap recap` по умолчанию удаляет ключи API вендоров
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
> news-recap recap --use-api-key
> ```

- `NEWS_RECAP_LLM_DEFAULT_AGENT` — агент по умолчанию (`codex`, `claude` или `gemini`).
- `NEWS_RECAP_LLM_TASK_MODEL_MAP` — переопределения модели по типу задачи и агенту
  (`task_type:agent=model_flags,...`).

## Help

```bash
news-recap --help
news-recap ingest --help
news-recap recap --help
news-recap prompt --help
news-recap list --help
news-recap serve --help
```
