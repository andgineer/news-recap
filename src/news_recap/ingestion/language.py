"""Lightweight language detection for RU/SR/EN."""

from __future__ import annotations

import re

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SR_MARKERS_RE = re.compile(r"[љњђћџЈЊЂЋЏčćžšđČĆŽŠĐ]")
_RU_MARKERS_RE = re.compile(r"[ыэёЫЭЁъЪ]")


def detect_language(text: str, title: str = "") -> str:
    """Detect language using script and marker heuristics.

    Returns one of: ``ru``, ``sr``, ``en``, ``unknown``.
    """

    sample = f"{title} {text}".strip()
    if not sample:
        return "unknown"

    has_cyrillic = bool(_CYRILLIC_RE.search(sample))
    has_latin = bool(_LATIN_RE.search(sample))
    has_sr_markers = bool(_SR_MARKERS_RE.search(sample))

    language = "unknown"
    if has_cyrillic:
        if has_sr_markers:
            language = "sr"
        elif _RU_MARKERS_RE.search(sample):
            language = "ru"
        else:
            # Mixed Cyrillic without strong markers is usually Russian in the target stream.
            language = "ru"
    elif has_latin:
        language = "sr" if has_sr_markers else "en"

    return language
