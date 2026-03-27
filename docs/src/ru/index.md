# news-recap

`news-recap` — CLI-first система для:

- сбора новостей из RSS/Atom,
- нормализации и очистки текста статей,
- семантической дедупликации и кластеризации,
- генерации ежедневных дайджестов с помощью LLM-агентов (Codex, Claude Code, Gemini CLI),
- файлового хранения статей и дайджестов.

## Текущий Scope

- Ingestion из RSS/Atom (включая Inoreader Output RSS).
- Файловое хранение статей с ежедневным разбиением и автоматической сборкой мусора.
- Recap-пайплайн в двух режимах:
    - **Map-reduce** (по умолчанию): classify → load_resources → enrich → deduplicate → map → reduce → split → group_sections → summarize.
    - **Oneshot** (`--oneshot`): classify → load_resources → enrich → deduplicate → oneshot_digest (параллельные батчи + детерминистический дедуп блоков + объединение секций) → refine_layout (опциональный LLM-проход для консолидации фрагментированных секций).

## С чего Начать

- Установка и окружение: `installation.md`
- Полный список CLI-команд и примеры: `cli.md`

## Дополнительно

Используйте:

```bash
news-recap --help
```

чтобы посмотреть полное дерево команд.
