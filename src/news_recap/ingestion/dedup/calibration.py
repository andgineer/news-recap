"""Golden-set utilities for dedup threshold calibration."""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

from news_recap.ingestion.dedup.embedder import build_embedder, cosine_similarity

MANDATORY_MODELS = (
    "intfloat/multilingual-e5-small",
    "intfloat/multilingual-e5-base",
)


@dataclass(slots=True)
class GoldenPair:
    """Labeled pair for dedup threshold calibration."""

    left_text: str
    right_text: str
    label: int


@dataclass(slots=True)
class ThresholdMetrics:
    """Precision/recall summary at a threshold."""

    threshold: float
    precision: float
    recall: float
    f1: float


@dataclass(slots=True)
class ModelBenchmark:
    """Benchmark result for one model candidate."""

    model_name: str
    mean_similarity_duplicate: float
    mean_similarity_non_duplicate: float
    throughput_pairs_per_second: float


def load_golden_pairs(path: Path) -> list[GoldenPair]:
    """Load golden set CSV with columns: left_text,right_text,label."""

    pairs: list[GoldenPair] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            pairs.append(
                GoldenPair(
                    left_text=row["left_text"],
                    right_text=row["right_text"],
                    label=int(row["label"]),
                ),
            )
    return pairs


def evaluate_threshold(
    pairs: list[GoldenPair],
    similarities: list[float],
    threshold: float,
) -> ThresholdMetrics:
    """Compute precision/recall/F1 for duplicate detection."""

    true_positive = false_positive = false_negative = 0

    for pair, similarity in zip(pairs, similarities, strict=True):
        predicted_duplicate = similarity >= threshold
        is_duplicate = bool(pair.label)
        if predicted_duplicate and is_duplicate:
            true_positive += 1
        elif predicted_duplicate and not is_duplicate:
            false_positive += 1
        elif (not predicted_duplicate) and is_duplicate:
            false_negative += 1

    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if (true_positive + false_negative)
        else 0.0
    )
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

    return ThresholdMetrics(threshold=threshold, precision=precision, recall=recall, f1=f1)


def pick_best_threshold(
    pairs: list[GoldenPair],
    similarities: list[float],
    candidates: list[float] | None = None,
) -> ThresholdMetrics:
    """Find threshold with best F1 among candidate values."""

    search_space = candidates or [round(value / 100, 2) for value in range(80, 100)]
    scored = [evaluate_threshold(pairs, similarities, threshold) for threshold in search_space]
    return sorted(scored, key=lambda metric: (-metric.f1, -metric.precision, -metric.recall))[0]


def benchmark_models(pairs: list[GoldenPair], model_names: list[str]) -> list[ModelBenchmark]:
    """Benchmark embedding models for quality separation and CPU throughput."""

    benchmarks: list[ModelBenchmark] = []
    for model_name in model_names:
        embedder = build_embedder(model_name)
        start = time.perf_counter()
        similarities: list[float] = []
        for pair in pairs:
            left, right = embedder.embed([pair.left_text, pair.right_text])
            similarities.append(cosine_similarity(left, right))
        elapsed = max(time.perf_counter() - start, 1e-9)

        duplicate_values = [
            value for pair, value in zip(pairs, similarities, strict=True) if pair.label == 1
        ]
        non_duplicate_values = [
            value for pair, value in zip(pairs, similarities, strict=True) if pair.label == 0
        ]
        duplicate_mean = sum(duplicate_values) / len(duplicate_values) if duplicate_values else 0.0
        non_duplicate_mean = (
            sum(non_duplicate_values) / len(non_duplicate_values) if non_duplicate_values else 0.0
        )

        benchmarks.append(
            ModelBenchmark(
                model_name=model_name,
                mean_similarity_duplicate=duplicate_mean,
                mean_similarity_non_duplicate=non_duplicate_mean,
                throughput_pairs_per_second=len(pairs) / elapsed,
            ),
        )

    return benchmarks
