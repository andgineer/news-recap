"""Output validation for JSON contract and strict source mapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from news_recap.orchestrator.models import FailureClass


@dataclass(slots=True)
class ValidationResult:
    """Result of output validation."""

    is_valid: bool
    failure_class: FailureClass | None
    error_summary: str | None
    payload: dict[str, Any] | None


def validate_output_contract(  # noqa: PLR0911
    *,
    output_path: Path,
    allowed_source_ids: set[str],
) -> ValidationResult:
    """Validate backend output contract and source mapping."""

    if not output_path.exists():
        return ValidationResult(
            is_valid=False,
            failure_class=FailureClass.OUTPUT_INVALID_JSON,
            error_summary=f"Output file not found: {output_path}",
            payload=None,
        )

    try:
        raw = json.loads(output_path.read_text("utf-8"))
    except json.JSONDecodeError as error:
        return ValidationResult(
            is_valid=False,
            failure_class=FailureClass.OUTPUT_INVALID_JSON,
            error_summary=f"Output is not valid JSON: {error}",
            payload=None,
        )

    if not isinstance(raw, dict):
        return ValidationResult(
            is_valid=False,
            failure_class=FailureClass.OUTPUT_INVALID_JSON,
            error_summary="Output must be a JSON object.",
            payload=None,
        )
    blocks = raw.get("blocks")
    if not isinstance(blocks, list):
        return ValidationResult(
            is_valid=False,
            failure_class=FailureClass.OUTPUT_INVALID_JSON,
            error_summary="Output must contain blocks array.",
            payload=None,
        )
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary=f"blocks[{index}] must be an object.",
                payload=None,
            )
        text = block.get("text")
        source_ids = block.get("source_ids")
        if not isinstance(text, str):
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary=f"blocks[{index}].text must be a string.",
                payload=None,
            )
        if not isinstance(source_ids, list) or not source_ids:
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.SOURCE_MAPPING_FAILED,
                error_summary=f"blocks[{index}] has empty or missing source_ids.",
                payload=None,
            )
        unknown = [item for item in source_ids if item not in allowed_source_ids]
        if unknown:
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.SOURCE_MAPPING_FAILED,
                error_summary=(
                    f"blocks[{index}] contains unknown source_ids: {', '.join(sorted(unknown))}"
                ),
                payload=None,
            )

    return ValidationResult(
        is_valid=True,
        failure_class=None,
        error_summary=None,
        payload=raw,
    )
