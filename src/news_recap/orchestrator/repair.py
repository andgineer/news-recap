"""Repair/degradation policy helpers for invalid task outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from news_recap.orchestrator.models import FailureClass


@dataclass(slots=True)
class RepairDecision:
    """Decision returned by repair policy."""

    should_repair: bool
    reason: str


def decide_repair(
    *,
    failure_class: FailureClass,
    repair_attempted_at: datetime | None,
) -> RepairDecision:
    """Allow one in-attempt repair for contract/mapping failures."""

    if failure_class not in {
        FailureClass.OUTPUT_INVALID_JSON,
        FailureClass.SOURCE_MAPPING_FAILED,
    }:
        return RepairDecision(
            should_repair=False,
            reason="Failure class is not repairable in-attempt.",
        )
    if repair_attempted_at is not None:
        return RepairDecision(
            should_repair=False,
            reason="Repair already attempted.",
        )
    return RepairDecision(should_repair=True, reason="One repair attempt is allowed.")
