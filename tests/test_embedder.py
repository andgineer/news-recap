from __future__ import annotations

import logging

import allure
import pytest

import news_recap.ingestion.dedup.embedder as embedder_module
from news_recap.ingestion.dedup.embedder import HashingEmbedder, build_embedder

pytestmark = [
    allure.epic("Dedup Quality"),
    allure.feature("Embeddings & Thresholding"),
]


class _BrokenSentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:  # noqa: ARG002
        raise ImportError("sentence-transformers is not available")


def test_build_embedder_raises_when_e5_backend_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        embedder_module,
        "SentenceTransformerEmbedder",
        _BrokenSentenceTransformerEmbedder,
    )

    with pytest.raises(RuntimeError, match="Failed to initialize embedding model"):
        build_embedder("intfloat/multilingual-e5-small")


def test_build_embedder_fallback_can_be_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedder_module,
        "SentenceTransformerEmbedder",
        _BrokenSentenceTransformerEmbedder,
    )

    embedder = build_embedder(
        "intfloat/multilingual-e5-small",
        allow_fallback=True,
    )
    assert isinstance(embedder, HashingEmbedder)


def test_hf_warning_filter_suppresses_only_target_message() -> None:
    warning_filter = embedder_module._HfHubUnauthWarningFilter()
    warning_record = logging.LogRecord(
        name="huggingface_hub.utils._http",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=(
            "Warning: You are sending unauthenticated requests to the HF Hub. "
            "Please set a HF_TOKEN to enable higher rate limits and faster downloads."
        ),
        args=(),
        exc_info=None,
    )
    other_record = logging.LogRecord(
        name="huggingface_hub.utils._http",
        level=logging.WARNING,
        pathname=__file__,
        lineno=2,
        msg="Rate limited. Waiting 1.0s before retry [Retry 1/5].",
        args=(),
        exc_info=None,
    )

    assert warning_filter.filter(warning_record) is False
    assert warning_filter.filter(other_record) is True
