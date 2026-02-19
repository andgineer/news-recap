# news-recap

`news-recap` — CLI-first система для:

- сбора новостей из RSS/Atom,
- нормализации и очистки текста статей,
- семантической дедупликации и кластеризации,
- очереди LLM-задач и worker runtime,
- генерации stories/highlights/Q&A,
- трекинга read-state и feedback,
- хранения истории и артефактов в SQLite.

## Текущий Scope

- Ingestion из RSS/Atom (включая Inoreader Output RSS).
- Shared-хранение статей и user-scoped retrieval.
- Очередь задач для внешних CLI-агентов.
- Назначение сюжетов, генерация highlights, monitor answers, ad-hoc QA.
- Сохранение бизнес-output и команды наблюдаемости.

## С чего Начать

- Установка и окружение: `installation.md`
- Полный список CLI-команд и примеры: `cli.md`

## Дополнительно

Используйте:

```bash
news-recap --help
```

чтобы посмотреть полное дерево команд.
