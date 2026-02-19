"""Token cost estimation helpers for LLM task attempts."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class ModelPricing:
    """Per-model input/output pricing in USD per 1M tokens."""

    input_per_1m: float
    output_per_1m: float


def estimate_cost_usd(
    *,
    agent: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
) -> float | None:
    """Estimate task cost in USD from token usage and configured pricing."""

    pricing = _lookup_pricing(agent=agent, model=model)
    if pricing is None:
        return None

    if prompt_tokens is not None and completion_tokens is not None:
        return (
            (prompt_tokens / 1_000_000) * pricing.input_per_1m
            + (completion_tokens / 1_000_000) * pricing.output_per_1m
        )

    if total_tokens is not None:
        return (total_tokens / 1_000_000) * pricing.input_per_1m
    return None


def _lookup_pricing(*, agent: str, model: str) -> ModelPricing | None:
    mapping = _parse_pricing_mapping(os.getenv("NEWS_RECAP_LLM_PRICING", ""))
    direct = mapping.get((agent.strip().lower(), model.strip()))
    if direct is not None:
        return direct

    wildcard_model = mapping.get((agent.strip().lower(), "*"))
    if wildcard_model is not None:
        return wildcard_model

    global_default = mapping.get(("*", "*"))
    if global_default is not None:
        return global_default
    return None


def _parse_pricing_mapping(raw: str) -> dict[tuple[str, str], ModelPricing]:
    """Parse `NEWS_RECAP_LLM_PRICING` mapping.

    Format:
    - `agent:model:input_per_1m:output_per_1m`
    - multiple entries separated by `,`
    - supports wildcards in agent/model (`*`)
    """

    parsed: dict[tuple[str, str], ModelPricing] = {}
    if not raw.strip():
        return parsed

    for entry in raw.split(","):
        value = entry.strip()
        if not value:
            continue
        parts = [part.strip() for part in value.split(":")]
        if len(parts) != 4:
            continue
        agent, model, input_price, output_price = parts
        try:
            input_per_1m = float(input_price)
            output_per_1m = float(output_price)
        except ValueError:
            continue
        parsed[(agent.lower(), model)] = ModelPricing(
            input_per_1m=input_per_1m,
            output_per_1m=output_per_1m,
        )
    return parsed
