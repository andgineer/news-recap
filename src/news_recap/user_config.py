"""Persistent user configuration backed by a JSON file in data_dir."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from news_recap.recap.models import UserPreferences
from news_recap.storage.io import atomic_write

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = "config.json"
_KNOWN_KEYS = frozenset({"language", "exclude", "follow", "default_agent"})
DEFAULT_AGENT = "codex"


class UserConfigManager:
    """Read/write ``config.json`` inside the application data directory.

    The config file stores user-facing preferences (language, exclude, follow)
    and the default LLM agent.  All fields are optional — missing keys fall
    back to code defaults in ``UserPreferences``.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    @property
    def config_path(self) -> Path:
        return self._data_dir / _CONFIG_FILENAME

    def load(self) -> dict[str, str]:
        """Return config dict, or empty dict when the file is missing/corrupt."""
        path = self.config_path
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text("utf-8"))
            if not isinstance(raw, dict):
                return {}
            return {k: v for k, v in raw.items() if k in _KNOWN_KEYS and isinstance(v, str)}
        except (OSError, json.JSONDecodeError, ValueError):
            logger.warning("Could not read config file %s, using defaults", path)
            return {}

    def save(self, data: dict[str, str]) -> None:
        """Atomically write *data* to the config file (mkdir -p included)."""
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        atomic_write(self.config_path, payload)

    def build_preferences(
        self,
        *,
        language_override: str | None = None,
        exclude_override: str | None = None,
        follow_override: str | None = None,
    ) -> UserPreferences:
        """Build ``UserPreferences`` applying CLI > config file > code defaults.

        Each tier is checked with ``is not None`` so that an explicit empty
        string (e.g. ``exclude=""`` in the config) is honoured rather than
        falling through to the next tier.
        """
        cfg = self.load()
        defaults = UserPreferences()

        def _pick(override: str | None, key: str, default: str) -> str:
            if override is not None:
                return override
            val = cfg.get(key)
            if val is not None:
                return val
            return default

        return UserPreferences(
            language=_pick(language_override, "language", defaults.language),
            exclude=_pick(exclude_override, "exclude", defaults.exclude),
            follow=_pick(follow_override, "follow", defaults.follow),
        )
