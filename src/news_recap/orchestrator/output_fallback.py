"""Best-effort output contract recovery from backend stdout."""

from __future__ import annotations

import json
import re

from news_recap.orchestrator.contracts import AgentOutputBlock, AgentOutputContract

STDOUT_PARSER_VERSION = "v1"

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def recover_output_contract_from_stdout(
    *,
    stdout_text: str,
    allowed_source_ids: set[str],
) -> AgentOutputContract | None:
    """Try to recover an `AgentOutputContract` from plain backend stdout."""

    text = stdout_text.strip()
    if not text:
        return None

    payload = _parse_json_payload(text)
    if payload is not None:
        normalized = _normalize_payload(payload=payload, allowed_source_ids=allowed_source_ids)
        if normalized is not None:
            return normalized

    fallback_source_id = _fallback_source_id(allowed_source_ids)
    if fallback_source_id is None:
        return None
    plain_text = _normalize_plain_text(text)
    if not plain_text:
        return None
    return AgentOutputContract(
        blocks=[
            AgentOutputBlock(
                text=plain_text,
                source_ids=[fallback_source_id],
            ),
        ],
        metadata={
            "stdout_parser": "plain_text_single_block",
            "stdout_parser_version": STDOUT_PARSER_VERSION,
        },
    )


def _parse_json_payload(text: str) -> dict[str, object] | None:
    direct = _try_load_dict(text)
    if direct is not None:
        return direct

    fenced = _FENCED_JSON.search(text)
    if fenced is not None:
        payload = _try_load_dict(fenced.group(1))
        if payload is not None:
            return payload

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return _try_load_dict(text[start : end + 1])


def _try_load_dict(raw: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalize_payload(  # noqa: C901
    *,
    payload: dict[str, object],
    allowed_source_ids: set[str],
) -> AgentOutputContract | None:
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list):
        return None
    fallback_source = _fallback_source_id(allowed_source_ids)
    if fallback_source is None:
        return None

    blocks: list[AgentOutputBlock] = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        source_ids_raw = item.get("source_ids")
        source_ids: list[str] = []
        if isinstance(source_ids_raw, list):
            seen: set[str] = set()
            for source_id in source_ids_raw:
                if not isinstance(source_id, str):
                    continue
                if source_id not in allowed_source_ids or source_id in seen:
                    continue
                seen.add(source_id)
                source_ids.append(source_id)
        if not source_ids:
            source_ids = [fallback_source]
        blocks.append(AgentOutputBlock(text=text.strip(), source_ids=source_ids))

    if not blocks:
        return None
    metadata: dict[str, object] = {}
    raw_metadata = payload.get("metadata")
    if isinstance(raw_metadata, dict):
        metadata = dict(raw_metadata)
    metadata["stdout_parser"] = "json_payload_normalized"
    metadata["stdout_parser_version"] = STDOUT_PARSER_VERSION
    return AgentOutputContract(blocks=blocks, metadata=metadata)


def _fallback_source_id(allowed_source_ids: set[str]) -> str | None:
    if not allowed_source_ids:
        return None
    return sorted(allowed_source_ids)[0]


def _normalize_plain_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    compact = "\n".join(line for line in lines if line.strip())
    return compact.strip()
