"""Direct Anthropic SDK transport for the API execution backend."""

from __future__ import annotations

import anthropic

from news_recap.recap.agents.transport import (
    LLMResponse,
    TransportOverloadedError,
    TransportRateLimitError,
)


class DirectAnthropicTransport:
    """Call Anthropic's messages API directly via the ``anthropic`` SDK."""

    def complete(self, *, model: str, prompt: str, timeout: int) -> LLMResponse:
        try:
            client = anthropic.Anthropic()
            message = client.messages.create(
                model=model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )
        except Exception as err:  # noqa: BLE001
            err_type = type(err).__name__
            err_msg = str(err).lower()
            if err_type == "RateLimitError" or isinstance(err, anthropic.RateLimitError):
                raise TransportRateLimitError(str(err)) from err
            if (
                err_type == "InternalServerError" or isinstance(err, anthropic.InternalServerError)
            ) and "overloaded" in err_msg:
                raise TransportOverloadedError(str(err)) from err
            raise

        first = message.content[0] if message.content else None
        content = first.text if isinstance(first, anthropic.types.TextBlock) else ""
        return LLMResponse(
            content=content,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            finish_reason=message.stop_reason or "unknown",
        )
