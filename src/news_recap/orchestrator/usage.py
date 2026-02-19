"""Usage extraction helpers for CLI agent output streams."""

from __future__ import annotations

import re
from dataclasses import dataclass

USAGE_PARSER_VERSION = "v1"

_JSON_PROMPT_TOKENS = re.compile(r'"prompt_tokens"\s*:\s*(\d+)', re.IGNORECASE)
_JSON_COMPLETION_TOKENS = re.compile(r'"completion_tokens"\s*:\s*(\d+)', re.IGNORECASE)
_JSON_TOTAL_TOKENS = re.compile(r'"total_tokens"\s*:\s*(\d+)', re.IGNORECASE)

_CODEx_TOKENS_USED = re.compile(r"tokens used\s*[\r\n ]+\s*([\d,]+)", re.IGNORECASE)
_INPUT_TOKENS = re.compile(r"input[_ ]tokens?\s*[:=]\s*([\d,]+)", re.IGNORECASE)
_OUTPUT_TOKENS = re.compile(r"(?:output|completion)[_ ]tokens?\s*[:=]\s*([\d,]+)", re.IGNORECASE)
_TOTAL_TOKENS = re.compile(r"total[_ ]tokens?\s*[:=]\s*([\d,]+)", re.IGNORECASE)


@dataclass(slots=True)
class UsageExtraction:
    """Best-effort token usage extraction result."""

    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_status: str
    usage_source: str
    parser_version: str
    reason: str | None = None


def extract_usage(*, agent: str, stdout: str, stderr: str) -> UsageExtraction:
    """Extract token usage from structured or textual backend output."""

    structured = _extract_structured(stdout=stdout, stderr=stderr)
    if structured is not None:
        return structured

    textual = _extract_textual(agent=agent, stdout=stdout, stderr=stderr)
    if textual is not None:
        return textual

    return UsageExtraction(
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        usage_status="unknown",
        usage_source="none",
        parser_version=USAGE_PARSER_VERSION,
        reason="no_usage_markers",
    )


def _extract_structured(*, stdout: str, stderr: str) -> UsageExtraction | None:
    for source_name, text in (("agent_stdout", stdout), ("agent_stderr", stderr)):
        prompt = _extract_int(_JSON_PROMPT_TOKENS, text)
        completion = _extract_int(_JSON_COMPLETION_TOKENS, text)
        total = _extract_int(_JSON_TOTAL_TOKENS, text)
        if prompt is None and completion is None and total is None:
            continue
        if total is None:
            known = [value for value in (prompt, completion) if value is not None]
            total = sum(known) if known else None
        return UsageExtraction(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            usage_status="reported",
            usage_source=source_name,
            parser_version=USAGE_PARSER_VERSION,
        )
    return None


def _extract_textual(*, agent: str, stdout: str, stderr: str) -> UsageExtraction | None:
    prompt = None
    completion = None
    total = None

    for source_name, text in (("agent_stderr", stderr), ("agent_stdout", stdout)):
        if total is None:
            total = _extract_int(_TOTAL_TOKENS, text)
        if prompt is None:
            prompt = _extract_int(_INPUT_TOKENS, text)
        if completion is None:
            completion = _extract_int(_OUTPUT_TOKENS, text)

        if total is None and agent == "codex":
            total = _extract_int(_CODEx_TOKENS_USED, text)

        if prompt is None and completion is None and total is None:
            continue

        if total is None:
            known = [value for value in (prompt, completion) if value is not None]
            total = sum(known) if known else None

        return UsageExtraction(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            usage_status="reported" if total is not None else "estimated",
            usage_source=source_name,
            parser_version=USAGE_PARSER_VERSION,
        )
    return None


def _extract_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    if match is None:
        return None
    raw = match.group(1).replace(",", "").strip()
    if not raw.isdigit():
        return None
    try:
        return int(raw)
    except ValueError:
        return None
