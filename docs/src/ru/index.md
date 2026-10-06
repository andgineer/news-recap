# news-recap

`news-recap` собирает статьи из RSS/Atom и превращает их в удобные для чтения дайджесты.

Создание дайджестов запускать по расписанию, ночью.

Использует CLI-агенты — ChatGPT Codex, Claude Code, Antigravity CLI — и работает
в рамках подписок с фиксированной ценой.

При ежедневном использовании за 7 дней расходуется примерно 20% недельного лимита
подписки Claude, а для ChatGPT — около 10%.

На бесплатном тарифе Antigravity CLI он работает полностью бесплатно.
Качество немного ниже, а лимит время от времени исчерпывается, поэтому в некоторые дни
дайджест не создаётся.

Для сравнения, Inoreader за ИИ-агрегацию берёт дополнительно \$19.90/мес **сверх**
Pro-подписки.

## Быстрый старт

Бесплатный вариант не требует ключей API: установите
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) и
[Antigravity CLI](https://antigravity.google/) (`agy`, вход через аккаунт Google), затем
установите `news-recap`:

```bash
uv tool install news-recap --upgrade --python 3.13
```

Получите RSS-ссылку. Пример для Inoreader: откройте контекстное меню папки, выберите
`Properties` и скопируйте RSS-ссылку оттуда.

Сохраните её в настройках и создайте дайджест:

```bash
news-recap config set rss "https://www.inoreader.com/stream/..."
news-recap ingest
news-recap create
news-recap serve
```

`news-recap config` показывает файл настроек (`~/.news_recap_data/config.toml`): язык,
исключаемые и отслеживаемые темы, агент, фиды. Чтобы вместо бесплатного агента работать по
подписке: `news-recap config set agent claude` (или `codex`).

Или настройте расписание (подробнее в [Запуск по расписанию](automation.md)):

```bash
news-recap schedule set
```

Полный список команд: [CLI](cli.md).

## Дополнительно: Jev {#jev}

[TypeSafe Jev](https://docs.typesafe.ai/) может взять на себя два решения «да/нет» вместо LLM:
какие заголовки исключить или переписать (`classify_backend`) и какие статьи — дубликаты
(`dedup_backend`). Нужен платный ключ API (для classify заметно меньше \$1 в месяц, для dedup
около \$0.75); он экономит запуски агента, что важно на бесплатном тарифе Antigravity.

Положите ключ в `~/.news_recap_data/.env` (не в `config.toml`):

```bash
echo "TYPESAFE_API_KEY=..." >> ~/.news_recap_data/.env
news-recap config set classify_backend jev
news-recap config set dedup_backend jev
```

Jev читает исключаемые темы буквально, поэтому формулируйте их как предмет новости:
«Croatian domestic news», а не «Croatian news». Без ключа оба шага остаются на LLM.
