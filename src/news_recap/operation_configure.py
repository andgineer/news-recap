"""Interactive ``configure`` command — view and edit persistent user preferences."""

from __future__ import annotations

from collections.abc import Iterator

import click

from news_recap.config import Settings
from news_recap.recap.models import UserPreferences
from news_recap.user_config import DEFAULT_AGENT, UserConfigManager

ConfigureLine = tuple[str, str]

_SUPPORTED_AGENTS = ("codex", "claude", "gemini")

_FIELDS: list[tuple[str, str]] = [
    ("language", "Language"),
    ("exclude", "Exclude"),
    ("follow", "Follow"),
    ("default_agent", "Default Agent"),
]


def _effective_value(cfg: dict[str, str], key: str) -> tuple[str, bool]:
    """Return ``(value, from_config)``."""
    if key in cfg:
        return cfg[key], True
    defaults = UserPreferences()
    code_defaults: dict[str, str] = {
        "language": defaults.language,
        "exclude": defaults.exclude,
        "follow": defaults.follow,
        "default_agent": DEFAULT_AGENT,
    }
    return code_defaults.get(key, ""), False


def _parse_selection(raw: str) -> tuple[list[int], list[ConfigureLine]]:
    """Parse user selection into field indices and any warning lines."""
    warnings: list[ConfigureLine] = []
    if raw.lower() == "all":
        return list(range(len(_FIELDS))), warnings
    indices: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            idx = int(token) - 1
        except ValueError:
            warnings.append(("warn", f"Ignoring invalid selection: {token!r}"))
            continue
        if 0 <= idx < len(_FIELDS):
            indices.append(idx)
        else:
            warnings.append(("warn", f"Ignoring out-of-range selection: {token}"))
    return indices, warnings


def _prompt_field(key: str, label: str, current: str) -> str:
    """Prompt the user for a single field value."""
    if key == "default_agent":
        return click.prompt(
            label,
            default=current,
            type=click.Choice(_SUPPORTED_AGENTS, case_sensitive=False),
            show_choices=True,
        )
    return click.prompt(label, default=current)


def operation_configure() -> Iterator[ConfigureLine]:
    """Run the interactive configure flow, yielding styled output lines."""
    settings = Settings.from_env()
    mgr = UserConfigManager(settings.data_dir)
    cfg = mgr.load()

    yield ("heading", "Configuration")
    yield ("log", f"Config file: {mgr.config_path}")
    yield ("info", "")
    yield ("info", "Current settings:")

    for i, (key, label) in enumerate(_FIELDS, 1):
        value, from_config = _effective_value(cfg, key)
        suffix = "" if from_config else " (default)"
        yield ("info", f"  {i}. {label + ':':<16}{value}{suffix}")

    yield ("info", "")
    raw = click.prompt(
        "Select fields to update (comma-separated numbers, 'all', or Enter to skip)",
        default="",
        show_default=False,
    ).strip()

    if not raw:
        yield ("log", "No changes.")
        return

    indices, warnings = _parse_selection(raw)
    yield from warnings

    if not indices:
        yield ("log", "No valid fields selected.")
        return

    yield ("info", "")
    for idx in indices:
        key, label = _FIELDS[idx]
        current, _ = _effective_value(cfg, key)
        cfg[key] = _prompt_field(key, label, current)

    mgr.save(cfg)
    yield ("ok", "Configuration saved.")
