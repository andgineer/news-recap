"""LLM transport protocol and standard response/error types."""

from __future__ import annotations

from typing import NamedTuple, Protocol


class LLMResponse(NamedTuple):
    content: str
    input_tokens: int
    output_tokens: int
    finish_reason: str


class LLMTransport(Protocol):
    def complete(self, *, model: str, prompt: str, timeout: int) -> LLMResponse: ...


class TransportRateLimitError(Exception):
    """Rate limit / 429 from the upstream API."""


class TransportOverloadedError(Exception):
    """Service temporarily overloaded."""
