from __future__ import annotations

import allure

from news_recap.orchestrator.sanitization import sanitize_preview
from news_recap.orchestrator.usage import extract_usage

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Attempt Telemetry"),
]


def test_sanitize_preview_redacts_secret_patterns() -> None:
    raw = (
        "Authorization: Bearer abcdef1234567890\n"
        "OPENAI_API_KEY=sk-secret-12345\n"
        "mail=user@example.com\n"
        "url=https://example.com?q=1&token=abcd"
    )
    sanitized = sanitize_preview(raw)
    assert "abcdef1234567890" not in sanitized
    assert "sk-secret-12345" not in sanitized
    assert "user@example.com" not in sanitized
    assert "token=abcd" not in sanitized


def test_extract_usage_reads_codex_tokens_used_pattern() -> None:
    usage = extract_usage(
        agent="codex",
        stdout="",
        stderr="tokens used\n48,017\n",
    )
    assert usage.total_tokens == 48017
    assert usage.usage_status == "reported"
    assert usage.usage_source in {"agent_stderr", "agent_stdout"}
    assert usage.parser_version == "v1"


def test_extract_usage_reads_structured_json_breakdown() -> None:
    usage = extract_usage(
        agent="codex",
        stdout='{"usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}}',
        stderr="",
    )
    assert usage.prompt_tokens == 120
    assert usage.completion_tokens == 30
    assert usage.total_tokens == 150
    assert usage.usage_status == "reported"
    assert usage.usage_source == "agent_stdout"


def test_extract_usage_structured_without_total_marks_estimated() -> None:
    usage = extract_usage(
        agent="codex",
        stdout='{"usage": {"prompt_tokens": 120, "completion_tokens": 30}}',
        stderr="",
    )
    assert usage.prompt_tokens == 120
    assert usage.completion_tokens == 30
    assert usage.total_tokens == 150
    assert usage.usage_status == "estimated"
    assert usage.usage_source == "agent_stdout"


def test_extract_usage_merges_textual_markers_from_stderr_and_stdout() -> None:
    usage = extract_usage(
        agent="codex",
        stdout="input tokens: 100\noutput tokens: 40\n",
        stderr="total tokens: 150\n",
    )
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 40
    assert usage.total_tokens == 150
    assert usage.usage_source == "both"


def test_extract_usage_textual_without_total_marks_estimated() -> None:
    usage = extract_usage(
        agent="codex",
        stdout="input tokens: 90\noutput tokens: 10\n",
        stderr="",
    )
    assert usage.prompt_tokens == 90
    assert usage.completion_tokens == 10
    assert usage.total_tokens == 100
    assert usage.usage_status == "estimated"
