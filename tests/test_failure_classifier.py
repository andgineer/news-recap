from __future__ import annotations

import allure

from news_recap.orchestrator.failure_classifier import (
    LLM_FAILURE_CLASSIFIER_VERSION,
    classify_backend_failure,
)
from news_recap.orchestrator.models import FailureClass

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Routing, Failures, CLI Ops"),
]


def test_classifier_version_is_stable() -> None:
    assert LLM_FAILURE_CLASSIFIER_VERSION == 1


def test_classifier_prefers_billing_over_transient_exit_code() -> None:
    classified = classify_backend_failure(
        agent="gemini",
        exit_code=137,
        stdout="",
        stderr="Quota exceeded for this project",
        transient_exit_codes=(137, 143),
    )
    assert classified.failure_class == FailureClass.BILLING_OR_QUOTA
    assert classified.matched_rule == "billing_or_quota"
    assert classified.matched_pattern == "quota"


def test_classifier_maps_model_unavailable() -> None:
    classified = classify_backend_failure(
        agent="claude",
        exit_code=1,
        stdout="",
        stderr="Invalid model requested",
        transient_exit_codes=(137, 143),
    )
    assert classified.failure_class == FailureClass.MODEL_NOT_AVAILABLE
    assert classified.reason_code == "claude_model_not_available"


def test_classifier_maps_rate_limit_to_backend_transient() -> None:
    classified = classify_backend_failure(
        agent="codex",
        exit_code=1,
        stdout="",
        stderr="HTTP 429 too many requests, please retry",
        transient_exit_codes=(137, 143),
    )
    assert classified.failure_class == FailureClass.BACKEND_TRANSIENT
    assert classified.matched_rule == "rate_limit_transient"


def test_classifier_falls_back_to_non_retryable() -> None:
    classified = classify_backend_failure(
        agent="codex",
        exit_code=2,
        stdout="fatal: unsupported syntax in prompt template",
        stderr="",
        transient_exit_codes=(137, 143),
    )
    assert classified.failure_class == FailureClass.BACKEND_NON_RETRYABLE
    assert classified.matched_rule == "fallback_non_retryable"
