"""Embedding abstractions for semantic deduplication."""

from __future__ import annotations

import hashlib
import logging
import math
import re
from array import array
from dataclasses import dataclass, field
from typing import Any, Protocol

Vector = list[float]
_HF_UNAUTH_WARNING_PATTERN = re.compile(
    r"^Warning:\s*You are sending unauthenticated requests to the HF Hub\.",
)


class _HfHubUnauthWarningFilter(logging.Filter):
    """Suppress one noisy HF Hub unauthenticated warning line."""

    def filter(self, record: logging.LogRecord) -> bool:
        return _HF_UNAUTH_WARNING_PATTERN.match(record.getMessage()) is None


def _suppress_hf_hub_unauth_warning() -> None:
    logger = logging.getLogger("huggingface_hub.utils._http")
    if any(isinstance(item, _HfHubUnauthWarningFilter) for item in logger.filters):
        return
    logger.addFilter(_HfHubUnauthWarningFilter())


class Embedder(Protocol):
    """Embedding backend interface."""

    model_name: str

    def embed(self, texts: list[str]) -> list[Vector]:
        """Encode texts into normalized vectors."""
        raise NotImplementedError


@dataclass(slots=True)
class HashingEmbedder:
    """CPU-friendly fallback embedder based on hashed character n-grams."""

    model_name: str
    dimensions: int = 384
    ngram_size: int = 3

    def embed(self, texts: list[str]) -> list[Vector]:
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text: str) -> Vector:
        normalized = (text or "").lower().strip()
        vector = array("f", [0.0]) * self.dimensions
        if not normalized:
            return list(vector)

        if len(normalized) < self.ngram_size:
            normalized = normalized + " " * (self.ngram_size - len(normalized))

        for index in range(len(normalized) - self.ngram_size + 1):
            ngram = normalized[index : index + self.ngram_size]
            digest = hashlib.sha1(ngram.encode("utf-8"), usedforsecurity=False).digest()  # noqa: S324
            bucket = int.from_bytes(digest[:4], byteorder="little") % self.dimensions
            vector[bucket] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = array("f", (value / norm for value in vector))
        return list(vector)


@dataclass(slots=True)
class SentenceTransformerEmbedder:
    """Sentence-transformers backend with lazy import."""

    model_name: str
    _model: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _suppress_hf_hub_unauth_warning()
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer(self.model_name)

    def embed(self, texts: list[str]) -> list[Vector]:
        prefixed = [f"passage: {text}" for text in texts]
        vectors = self._model.encode(prefixed, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]


def build_embedder(model_name: str, *, allow_fallback: bool = False) -> Embedder:
    """Build the configured embedder.

    For multilingual E5 models, fallback is explicit to avoid silent quality degradation.
    """

    if model_name.startswith("intfloat/multilingual-e5"):
        try:
            return SentenceTransformerEmbedder(model_name=model_name)
        except (ImportError, ModuleNotFoundError, OSError, RuntimeError, ValueError) as error:
            if allow_fallback:
                return HashingEmbedder(model_name=model_name)
            raise RuntimeError(
                f"Failed to initialize embedding model {model_name}. "
                "Install sentence-transformers or set "
                "NEWS_RECAP_DEDUP_ALLOW_MODEL_FALLBACK=true.",
            ) from error
    return HashingEmbedder(model_name=model_name)


def cosine_similarity(left: Vector, right: Vector) -> float:
    """Compute cosine similarity for normalized vectors."""

    if len(left) != len(right):
        raise ValueError("Vectors must have the same size")

    dot = sum(l_value * r_value for l_value, r_value in zip(left, right, strict=True))
    return max(-1.0, min(1.0, dot))
