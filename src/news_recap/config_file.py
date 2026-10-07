"""``config.toml`` in the data directory: the key table, template, loading and ``config set``."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import tomlkit
from tomlkit.items import String, StringType, Trivia

from news_recap.recap.jev.policy import split_policy_topics
from news_recap.storage.io import atomic_write

if TYPE_CHECKING:
    from news_recap.config import Settings

CONFIG_FILENAME = "config.toml"


class ConfigError(ValueError):
    """A setting in ``config.toml`` (or derived from it) is invalid."""


AGENTS = ("antigravity", "codex", "claude")
STEP_BACKENDS = ("llm", "jev")


@dataclass(frozen=True, slots=True)
class Key:
    """One setting: where it sits in the file, which ``Settings`` attribute it sets, its type."""

    name: str
    target: str  # dotted attribute path inside ``Settings``
    kind: type
    comment: str = ""
    choices: tuple[str, ...] = ()
    multiline: bool = False


TOP_LEVEL: tuple[Key, ...] = (
    Key(
        "language",
        "preferences.language",
        str,
        "Digest language: a BCP-47 code such as en, ru, sr, hr, de.",
    ),
    Key(
        "exclude",
        "preferences.exclude",
        str,
        "Topics to drop, one per line. A note in parentheses is an exception.",
        multiline=True,
    ),
    Key(
        "follow",
        "preferences.follow",
        str,
        "Topics that get their own sections, one per line.",
        multiline=True,
    ),
    Key(
        "agent",
        "orchestrator.default_agent",
        str,
        "LLM agent CLI: antigravity (free Gemini tier, no keys) | codex | claude",
        choices=AGENTS,
    ),
    Key("rss", "rss.feed_urls", list, "RSS/Atom feed URLs."),
    Key(
        "classify_backend",
        "jev.classify_backend",
        str,
        "Exclude/vague decisions: llm | jev (jev needs TYPESAFE_API_KEY in .env)",
        choices=STEP_BACKENDS,
    ),
    Key(
        "dedup_backend",
        "jev.dedup_backend",
        str,
        "Duplicate detection: llm | jev (jev needs TYPESAFE_API_KEY in .env)",
        choices=STEP_BACKENDS,
    ),
)

SECTIONS: dict[str, tuple[Key, ...]] = {
    "ingestion": (
        Key(
            "lookback_days",
            "ingestion.digest_lookback_days",
            int,
            "Max days of articles in a digest.",
        ),
        Key(
            "retention_days",
            "ingestion.gc_retention_days",
            int,
            "Days of article partitions kept.",
        ),
        Key("page_size", "ingestion.page_size", int),
        Key("max_pages", "ingestion.max_pages", int),
        Key("backfill_max_gaps", "ingestion.backfill_max_gaps", int),
        Key("clean_text_max_chars", "ingestion.clean_text_max_chars", int),
        Key("min_resource_chars", "ingestion.min_resource_chars", int),
    ),
    "fetch": (
        Key("default_items_per_feed", "rss.default_items_per_feed", int),
        Key(
            "per_feed_items",
            "rss.per_feed_items",
            dict,
            'Items per feed URL, e.g. { "https://…" = 500 }.',
        ),
        Key("snapshot_max_age_hours", "rss.snapshot_max_age_hours", int),
        Key("max_retries", "rss.max_retries", int),
        Key("retry_backoff_seconds", "rss.retry_backoff_seconds", float),
        Key("request_timeout_seconds", "rss.request_timeout_seconds", float),
    ),
    "dedup": (
        Key(
            "threshold",
            "dedup.threshold",
            float,
            "Embedding similarity that makes a candidate group.",
        ),
        Key("model_name", "dedup.model_name", str),
    ),
    "llm": (
        Key("workdir_root", "orchestrator.workdir_root", str),
        Key(
            "execution_backend",
            "orchestrator.execution_backend",
            str,
            "cli | api",
            choices=("cli", "api"),
        ),
        Key("models", "orchestrator.task_model_map", dict, "Model flags per task and agent."),
    ),
    "api": (
        Key("model_map", "orchestrator.api_model_map", dict, "Model id per task (API mode)."),
        Key("max_parallel", "orchestrator.api_max_parallel", int),
        Key(
            "concurrency_recovery_successes",
            "orchestrator.api_concurrency_recovery_successes",
            int,
        ),
        Key("retry_max_backoff_seconds", "orchestrator.api_retry_max_backoff_seconds", float),
        Key("retry_jitter_seconds", "orchestrator.api_retry_jitter_seconds", float),
        Key("downshift_pause_seconds", "orchestrator.api_downshift_pause_seconds", float),
    ),
}

_TOP_LEVEL_BY_NAME = {k.name: k for k in TOP_LEVEL}
_KIND_NAMES = {
    str: "a string",
    int: "an integer",
    float: "a number",
    list: "a list",
    dict: "a table",
}


def config_path(data_dir: Path) -> Path:
    return data_dir / CONFIG_FILENAME


def read_attr(settings: Settings, target: str) -> Any:
    obj: Any = settings
    for part in target.split("."):
        obj = getattr(obj, part)
    return obj


def load_config_file(path: Path) -> list[tuple[Key, Any]]:
    """Return ``(key, value)`` for every setting the file sets; raise ``ValueError`` naming it."""
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    found: list[tuple[Key, Any]] = []
    for name, value in data.items():
        if name in SECTIONS:
            if not isinstance(value, dict):
                raise ConfigError(f"{path}: [{name}] must be a table")
            keys = {k.name: k for k in SECTIONS[name]}
            for sub, sub_value in value.items():
                if sub not in keys:
                    raise ConfigError(f"{path}: unknown key {name}.{sub}")
                found.append((keys[sub], _checked(path, f"{name}.{sub}", keys[sub], sub_value)))
        elif name in _TOP_LEVEL_BY_NAME:
            key = _TOP_LEVEL_BY_NAME[name]
            found.append((key, _checked(path, name, key, value)))
        else:
            raise ConfigError(f"{path}: unknown key {name}")
    return found


def _checked(path: Path, label: str, key: Key, value: Any) -> Any:
    kind_ok = (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        if key.kind is float
        else isinstance(value, key.kind) and not isinstance(value, bool)
    )
    if not kind_ok:
        raise ConfigError(f"{path}: {label} must be {_KIND_NAMES[key.kind]}, got {value!r}")
    if key.kind is list and not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{path}: {label} must be a list of strings")
    if key.kind is dict and not _table_shape_ok(key, value):
        raise ConfigError(f"{path}: {label}: {_TABLE_SHAPES[key.name]}")
    if key.choices and value not in key.choices:
        raise ConfigError(
            f"{path}: {label} must be one of {' | '.join(key.choices)}, got {value!r}",
        )
    return float(value) if key.kind is float else value


_TABLE_SHAPES = {
    "models": 'expected task.agent = "model flags" strings',
    "model_map": 'expected task = "model id" strings',
    "per_feed_items": 'expected "feed URL" = item count integers',
}


def _table_shape_ok(key: Key, value: dict[str, Any]) -> bool:
    if key.name == "models":
        return all(
            isinstance(agents, dict) and all(isinstance(f, str) for f in agents.values())
            for agents in value.values()
        )
    if key.name == "per_feed_items":
        return all(isinstance(v, int) and not isinstance(v, bool) for v in value.values())
    return all(isinstance(v, str) for v in value.values())


def render_template(defaults: Settings) -> str:
    """The file a new installation starts from: everyday keys set, advanced ones commented out."""
    doc = tomlkit.document()
    doc.add(
        tomlkit.comment(
            "news-recap settings. Edit this file or run `news-recap config set KEY VALUE`.",
        ),
    )
    doc.add(tomlkit.comment("Secrets (TYPESAFE_API_KEY) go in .env next to this file, never here."))
    for key in TOP_LEVEL:
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment(key.comment))
        doc.add(
            key.name,
            _top_level_item(key, _template_value(key, read_attr(defaults, key.target))),
        )
    doc.add(tomlkit.nl())
    doc.add(tomlkit.comment("Advanced: uncomment a line to override this release's default."))
    for section, keys in SECTIONS.items():
        table = tomlkit.table()
        for key in keys:
            if key.comment:
                table.add(tomlkit.comment(key.comment))
            for line in _commented_default(key, read_attr(defaults, key.target)):
                table.add(tomlkit.comment(line))
        doc.add(section, table)
    return doc.as_string()


def _template_value(key: Key, value: Any) -> Any:
    if key.multiline:
        return "\n".join(split_policy_topics(value))
    if key.kind is list:
        return list(value)
    return value


def _top_level_item(key: Key, value: Any) -> Any:
    if key.multiline:
        return _multiline(f"{value}\n" if value else "")
    return tomlkit.item(value)


def _multiline(value: str) -> String:
    # tomlkit puts the first line right after the opening quotes; a line break there is
    # dropped by TOML, so each topic gets its own line without changing the value.
    escaped = tomlkit.string(value, multiline=True).as_string()[3:-3]
    return String(StringType.MLB, value, f"\n{escaped}", Trivia())


def _commented_default(key: Key, value: Any) -> list[str]:
    if key.name == "models":
        return [
            f"models.{task}.{agent} = {tomlkit.item(entry['model']).as_string()}"
            for task, agents in value.items()
            for agent, entry in agents.items()
        ]
    if key.kind is dict:
        if not value:
            return [f"{key.name} = {{}}"]
        return [f"{key.name}.{name} = {tomlkit.item(v).as_string()}" for name, v in value.items()]
    shown = str(value) if isinstance(value, Path) else value
    return [f"{key.name} = {tomlkit.item(shown).as_string()}"]


def ensure_config_file(path: Path, defaults: Settings) -> bool:
    """Write the template when *path* is missing; return whether it was written."""
    if path.exists():
        return False
    atomic_write(path, render_template(defaults).encode("utf-8"))
    return True


def set_config_value(path: Path, defaults: Settings, name: str, values: Sequence[str]) -> Any:
    """Set top-level key *name* from command-line *values*, keeping the file's comments."""
    key = _TOP_LEVEL_BY_NAME.get(name)
    if key is None:
        raise ValueError(f"unknown key {name!r}; one of: {', '.join(_TOP_LEVEL_BY_NAME)}")
    value = _parse_cli_value(key, values)
    ensure_config_file(path, defaults)
    try:
        doc = tomlkit.parse(path.read_text("utf-8"))
    except tomlkit.exceptions.ParseError as error:
        raise ConfigError(f"{path}: {error}") from error
    doc[name] = _top_level_item(key, value)
    atomic_write(path, doc.as_string().encode("utf-8"))
    return value


def _parse_cli_value(key: Key, values: Sequence[str]) -> Any:
    if not values:
        raise ValueError(f"{key.name} needs a value")
    if key.kind is list:
        for url in values:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"not an http(s) URL: {url!r}")
        return list(values)
    if key.multiline:
        return "\n".join(v.strip() for v in values if v.strip())
    if len(values) > 1:
        raise ValueError(f"{key.name} takes one value")
    value = values[0].strip()
    if key.choices and value not in key.choices:
        raise ValueError(f"{key.name} must be one of {' | '.join(key.choices)}")
    return value


def top_level_values(path: Path) -> Mapping[str, Any]:
    """The everyday keys as the file sets them (absent keys are left out)."""
    return {key.name: value for key, value in load_config_file(path) if key in TOP_LEVEL}
