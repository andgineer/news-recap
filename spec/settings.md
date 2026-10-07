# Settings

news-recap is a desktop tool installed with `pip`/`uv tool install`, not a server, so its
settings live in a file the user owns, editable without the repository.

- **One file:** `config.toml` in the data directory (`~/.news_recap_data`). A missing file means
  the release defaults, and reading settings never writes it. `news-recap config` creates it
  from a template on first use and shows it; `news-recap config set` changes an everyday setting
  and keeps the rest of the file, comments included.
- **Everyday settings** are top-level and written with their values: language, topics to
  exclude and to follow (one per line), agent, feeds, and Jev per step. Settings with a fixed
  set of values carry a comment listing them.
- **Advanced settings** are grouped in sections and written commented out with the release's
  default, so the app follows each new release's defaults until the user uncomments a line.
- **Command-line flags** override the file for one run.
- **Defaults need no keys:** the free Antigravity agent, and Jev off for every step.
- **Environment variables carry only secrets:** the Jev key (also read from `.env` in the
  working or data directory, never exported to agents) and agent API keys. A data-directory
  override and two debug switches exist for development and tests; they are not user settings,
  and the scheduled run does not inherit them.
- **Every invalid setting stops the command with one line** naming the setting and the file:
  unknown names, wrong types, values outside their choices, malformed feed URLs, no feeds,
  invalid language codes and unreadable files.
- **The scheduled run follows the file:** `schedule set` fixes feeds or an agent into the job
  only when they are given on its command line.
