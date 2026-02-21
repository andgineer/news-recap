from __future__ import annotations

import allure

from news_recap.brain.pricing import estimate_cost_usd

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Attempt Telemetry"),
]


def test_estimate_cost_usd_uses_input_and_output_tokens(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_PRICING", "codex:gpt-test:1.0:3.0")
    cost = estimate_cost_usd(
        agent="codex",
        model="gpt-test",
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
        total_tokens=None,
    )
    assert cost == 2.5


def test_estimate_cost_usd_uses_average_price_for_total_tokens(monkeypatch) -> None:
    monkeypatch.setenv("NEWS_RECAP_LLM_PRICING", "codex:gpt-test:1.0:3.0")
    cost = estimate_cost_usd(
        agent="codex",
        model="gpt-test",
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=1_000_000,
    )
    assert cost == 2.0


def test_estimate_cost_usd_applies_wildcards(monkeypatch) -> None:
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_PRICING",
        "codex:*:2.0:2.0,*:*:9.0:9.0",
    )
    codex_cost = estimate_cost_usd(
        agent="codex",
        model="unknown-model",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        total_tokens=None,
    )
    claude_cost = estimate_cost_usd(
        agent="claude",
        model="unknown-model",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        total_tokens=None,
    )
    assert codex_cost == 2.0
    assert claude_cost == 9.0


def test_estimate_cost_usd_ignores_negative_price_rows(monkeypatch) -> None:
    monkeypatch.setenv(
        "NEWS_RECAP_LLM_PRICING",
        "codex:gpt-test:-1.0:2.0,*:*:4.0:4.0",
    )
    cost = estimate_cost_usd(
        agent="codex",
        model="gpt-test",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        total_tokens=None,
    )
    assert cost == 4.0
