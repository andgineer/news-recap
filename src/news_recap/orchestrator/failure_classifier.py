"""Deterministic backend failure classification for worker retry policy."""

from __future__ import annotations

from dataclasses import dataclass

from news_recap.orchestrator.models import FailureClass

LLM_FAILURE_CLASSIFIER_VERSION = 1

_BILLING_OR_QUOTA_PATTERNS: tuple[str, ...] = (
    "quota",
    "resource_exhausted",
    "insufficient",
    "billing",
    "payment",
    "credits",
    "usage limit",
    "exceeded",
)
_ACCESS_OR_AUTH_PATTERNS: tuple[str, ...] = (
    "unauthorized",
    "forbidden",
    "permission denied",
    "invalid api key",
    "authentication",
    "auth",
    "restricted token",
)
_MODEL_NOT_AVAILABLE_PATTERNS: tuple[str, ...] = (
    "model not found",
    "unknown model",
    "unsupported model",
    "invalid model",
    "model is not available",
    "not available in your region",
)
_RATE_LIMIT_TRANSIENT_PATTERNS: tuple[str, ...] = (
    "too many requests",
    "rate limit",
    "429",
    "please retry",
    "try again later",
)
_GENERIC_TRANSIENT_PATTERNS: tuple[str, ...] = (
    "temporarily unavailable",
    "temporary failure",
    "connection reset",
    "network error",
    "could not resolve host",
    "dns",
)


@dataclass(slots=True)
class BackendFailureClassification:
    """Normalized failure classification result."""

    failure_class: FailureClass
    reason_code: str
    matched_rule: str
    matched_pattern: str | None

    def to_event_details(self, *, agent: str, model: str) -> dict[str, object]:
        """Serialize classifier diagnostics for task events."""

        return {
            "classifier_version": LLM_FAILURE_CLASSIFIER_VERSION,
            "resolved_agent": agent,
            "resolved_model": model,
            "reason_code": self.reason_code,
            "matched_rule": self.matched_rule,
            "matched_pattern": self.matched_pattern,
        }


def classify_backend_failure(
    *,
    agent: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    transient_exit_codes: tuple[int, ...],
) -> BackendFailureClassification:
    """Classify non-timeout backend failure into deterministic retry class."""

    haystack = _normalize_text(stdout=stdout, stderr=stderr)

    pattern = _first_match(haystack, _BILLING_OR_QUOTA_PATTERNS)
    if pattern is not None:
        return BackendFailureClassification(
            failure_class=FailureClass.BILLING_OR_QUOTA,
            reason_code=f"{agent}_billing_or_quota",
            matched_rule="billing_or_quota",
            matched_pattern=pattern,
        )

    pattern = _first_match(haystack, _ACCESS_OR_AUTH_PATTERNS)
    if pattern is not None:
        return BackendFailureClassification(
            failure_class=FailureClass.ACCESS_OR_AUTH,
            reason_code=f"{agent}_access_or_auth",
            matched_rule="access_or_auth",
            matched_pattern=pattern,
        )

    pattern = _first_match(haystack, _MODEL_NOT_AVAILABLE_PATTERNS)
    if pattern is not None:
        return BackendFailureClassification(
            failure_class=FailureClass.MODEL_NOT_AVAILABLE,
            reason_code=f"{agent}_model_not_available",
            matched_rule="model_not_available",
            matched_pattern=pattern,
        )

    pattern = _first_match(haystack, _RATE_LIMIT_TRANSIENT_PATTERNS)
    if pattern is not None:
        return BackendFailureClassification(
            failure_class=FailureClass.BACKEND_TRANSIENT,
            reason_code=f"{agent}_rate_limit_transient",
            matched_rule="rate_limit_transient",
            matched_pattern=pattern,
        )

    pattern = _first_match(haystack, _GENERIC_TRANSIENT_PATTERNS)
    if pattern is not None or exit_code in transient_exit_codes:
        return BackendFailureClassification(
            failure_class=FailureClass.BACKEND_TRANSIENT,
            reason_code=f"{agent}_backend_transient",
            matched_rule=(
                "transient_exit_code"
                if exit_code in transient_exit_codes and pattern is None
                else "generic_transient"
            ),
            matched_pattern=pattern,
        )

    return BackendFailureClassification(
        failure_class=FailureClass.BACKEND_NON_RETRYABLE,
        reason_code=f"{agent}_backend_non_retryable",
        matched_rule="fallback_non_retryable",
        matched_pattern=None,
    )


def _normalize_text(*, stdout: str, stderr: str) -> str:
    return f"{stderr}\n{stdout}".lower()


def _first_match(haystack: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if pattern in haystack:
            return pattern
    return None
