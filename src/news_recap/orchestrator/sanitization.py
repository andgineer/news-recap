"""Sanitization helpers for attempt diagnostics persisted in DB."""

from __future__ import annotations

import re
from collections.abc import Callable

_MAX_PREVIEW_CHARS = 2_000

_Replacement = str | Callable[[re.Match[str]], str]

_REPLACEMENTS: tuple[tuple[re.Pattern[str], _Replacement], ...] = (
    (
        re.compile(r"(?i)\b(bearer)\s+[a-z0-9._\-]{8,}\b"),
        r"\1 [redacted-token]",
    ),
    (
        re.compile(r"(?i)\b(sk-[a-z0-9\-]{8,})\b"),
        "[redacted-token]",
    ),
    (
        re.compile(
            r"(?i)\b(news_recap|openai|anthropic|gemini|hf|huggingface)[a-z0-9_]*_?(api_)?(key|token)\b"
            r"\s*[:=]\s*['\"]?[^'\" \n\r\t]+['\"]?",
        ),
        "[redacted-secret]",
    ),
    (
        re.compile(r"(?i)([?&](?:token|key|signature|auth)=[^&\s]+)"),
        lambda match: match.group(1).split("=")[0] + "=[redacted]",
    ),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[redacted-email]",
    ),
)


def sanitize_preview(text: str, *, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    """Redact obvious secrets/PII and clamp payload size."""

    compact = text.strip()
    if not compact:
        return ""

    redacted = compact
    for pattern, replacement in _REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)

    if len(redacted) <= max_chars:
        return redacted
    return redacted[:max_chars]
