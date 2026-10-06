"""``config`` command — show ``config.toml`` (created on first use) and set its everyday keys."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import click

from news_recap.config import Settings, data_dir_from_env
from news_recap.config_file import (
    TOP_LEVEL,
    config_path,
    ensure_config_file,
    read_attr,
    set_config_value,
    top_level_values,
)

ConfigLine = tuple[str, str]


def show_config() -> Iterator[ConfigLine]:
    data_dir = data_dir_from_env()
    defaults = Settings.defaults(data_dir)
    path = config_path(data_dir)
    if ensure_config_file(path, defaults):
        yield ("ok", f"Created {path}")
    yield ("log", f"Config file: {path}")
    try:
        values = top_level_values(path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    for key in TOP_LEVEL:
        value = values.get(key.name, read_attr(defaults, key.target))
        suffix = "" if key.name in values else "  (default)"
        yield from _format(key.name, value, suffix)


def set_config(name: str, values: Sequence[str]) -> Iterator[ConfigLine]:
    data_dir = data_dir_from_env()
    path = config_path(data_dir)
    try:
        value = set_config_value(path, Settings.defaults(data_dir), name, values)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    yield from _format(name, value, "")
    yield ("ok", f"Saved to {path}")


def _format(name: str, value: Any, suffix: str) -> Iterator[ConfigLine]:
    if isinstance(value, str) and "\n" in value.strip():
        yield ("info", f"{name}:{suffix}")
        for line in value.strip().splitlines():
            yield ("info", f"    {line}")
    elif isinstance(value, (list, tuple)):
        yield ("info", f"{name}:{suffix}" if value else f"{name}: (none){suffix}")
        for item in value:
            yield ("info", f"    {item}")
    else:
        yield ("info", f"{name} = {value}{suffix}")
