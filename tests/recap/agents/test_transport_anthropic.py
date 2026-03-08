"""Tests for DirectAnthropicTransport."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from news_recap.recap.agents.transport import (
    LLMResponse,
    TransportOverloadedError,
    TransportRateLimitError,
)
from news_recap.recap.agents.transport_anthropic import DirectAnthropicTransport


def _mock_client(return_value=None, side_effect=None) -> MagicMock:
    client = MagicMock()
    if side_effect is not None:
        client.messages.create.side_effect = side_effect
    else:
        client.messages.create.return_value = return_value
    return client


def test_complete_returns_llm_response():
    text_block = anthropic.types.TextBlock(type="text", text="hello world")
    msg = MagicMock()
    msg.content = [text_block]
    msg.usage.input_tokens = 10
    msg.usage.output_tokens = 5
    msg.stop_reason = "end_turn"

    transport = DirectAnthropicTransport()
    with patch("anthropic.Anthropic", return_value=_mock_client(return_value=msg)):
        result = transport.complete(
            model="claude-haiku-4-5-20251001", prompt="say hello", timeout=30
        )

    assert isinstance(result, LLMResponse)
    assert result.content == "hello world"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.finish_reason == "end_turn"


def test_complete_raises_transport_rate_limit_error():
    FakeRateLimitError = type("RateLimitError", (Exception,), {})
    transport = DirectAnthropicTransport()

    with patch(
        "anthropic.Anthropic",
        return_value=_mock_client(side_effect=FakeRateLimitError("rate limit")),
    ):
        with pytest.raises(TransportRateLimitError):
            transport.complete(model="claude-haiku-4-5-20251001", prompt="x", timeout=30)


def test_complete_raises_transport_overloaded_error():
    FakeInternalServerError = type("InternalServerError", (Exception,), {})
    transport = DirectAnthropicTransport()

    with patch(
        "anthropic.Anthropic",
        return_value=_mock_client(
            side_effect=FakeInternalServerError("overloaded_error: service overloaded")
        ),
    ):
        with pytest.raises(TransportOverloadedError):
            transport.complete(model="claude-haiku-4-5-20251001", prompt="x", timeout=30)
