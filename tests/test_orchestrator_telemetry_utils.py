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
