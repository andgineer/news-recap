"""Output validation for JSON contract and strict source mapping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from news_recap.orchestrator.contracts import TaskManifest
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
    task_type: str = "",
    manifest: TaskManifest | None = None,
) -> ValidationResult:
    """Validate backend output contract and source mapping.

    For recap_* task types, delegates to task-specific validation that
    expects custom output schemas instead of the standard blocks[] format.
    """

    if task_type.startswith("recap_"):
        return _validate_recap_output(
            output_path=output_path,
            task_type=task_type,
            manifest=manifest,
        )

    return _validate_blocks_output(
        output_path=output_path,
        allowed_source_ids=allowed_source_ids,
    )


def _load_output_json(output_path: Path) -> ValidationResult | dict[str, Any]:
    """Load and parse agent_result.json, returning ValidationResult on error."""

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
    return raw


def _validate_blocks_output(  # noqa: PLR0911
    *,
    output_path: Path,
    allowed_source_ids: set[str],
) -> ValidationResult:
    """Validate the standard blocks[] output contract."""

    result = _load_output_json(output_path)
    if isinstance(result, ValidationResult):
        return result
    raw = result

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
                    f"blocks[{index}] contains unknown source_ids: "
                    f"{', '.join(sorted(unknown))}"
                ),
                payload=None,
            )

    return ValidationResult(
        is_valid=True,
        failure_class=None,
        error_summary=None,
        payload=raw,
    )


_RECAP_VALIDATORS: dict[str, str] = {
    "recap_classify": "articles",
    "recap_enrich": "enriched",
    "recap_enrich_full": "enriched",
    "recap_group": "events",
    "recap_synthesize": "status",
    "recap_compose": "theme_blocks",
}


def _validate_recap_output(  # noqa: PLR0911
    *,
    output_path: Path,
    task_type: str,
    manifest: TaskManifest | None,
) -> ValidationResult:
    """Validate recap pipeline task output based on task_type."""

    result = _load_output_json(output_path)
    if isinstance(result, ValidationResult):
        return result
    raw = result

    expected_key = _RECAP_VALIDATORS.get(task_type)
    if expected_key and expected_key not in raw:
        return ValidationResult(
            is_valid=False,
            failure_class=FailureClass.OUTPUT_INVALID_JSON,
            error_summary=f"Recap output for {task_type} must contain '{expected_key}' key.",
            payload=None,
        )

    if task_type == "recap_classify":
        articles = raw.get("articles")
        if not isinstance(articles, list) or not articles:
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary="recap_classify output.articles must be a non-empty array.",
                payload=None,
            )
        for idx, item in enumerate(articles):
            if not isinstance(item, dict):
                return ValidationResult(
                    is_valid=False,
                    failure_class=FailureClass.OUTPUT_INVALID_JSON,
                    error_summary=f"recap_classify articles[{idx}] must be an object.",
                    payload=None,
                )
            if "article_id" not in item or "decision" not in item:
                return ValidationResult(
                    is_valid=False,
                    failure_class=FailureClass.OUTPUT_INVALID_JSON,
                    error_summary=(
                        f"recap_classify articles[{idx}] missing article_id or decision."
                    ),
                    payload=None,
                )

    elif task_type == "recap_group":
        events = raw.get("events")
        if not isinstance(events, list) or not events:
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary="recap_group output.events must be a non-empty array.",
                payload=None,
            )
        for idx, event in enumerate(events):
            if not isinstance(event, dict):
                return ValidationResult(
                    is_valid=False,
                    failure_class=FailureClass.OUTPUT_INVALID_JSON,
                    error_summary=f"recap_group events[{idx}] must be an object.",
                    payload=None,
                )
            if "event_id" not in event or "article_ids" not in event:
                return ValidationResult(
                    is_valid=False,
                    failure_class=FailureClass.OUTPUT_INVALID_JSON,
                    error_summary=f"recap_group events[{idx}] missing event_id or article_ids.",
                    payload=None,
                )

    elif task_type == "recap_compose":
        theme_blocks = raw.get("theme_blocks")
        if not isinstance(theme_blocks, list) or not theme_blocks:
            return ValidationResult(
                is_valid=False,
                failure_class=FailureClass.OUTPUT_INVALID_JSON,
                error_summary="recap_compose output.theme_blocks must be a non-empty array.",
                payload=None,
            )

    return ValidationResult(
        is_valid=True,
        failure_class=None,
        error_summary=None,
        payload=raw,
    )
