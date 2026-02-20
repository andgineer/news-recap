"""Observability and benchmark metrics for orchestrator runtime."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from news_recap.orchestrator.models import (
    LlmTaskAttemptView,
    LlmTaskEventView,
    LlmTaskStatus,
    LlmTaskView,
)

_TERMINAL_STATUSES = {
    LlmTaskStatus.SUCCEEDED,
    LlmTaskStatus.FAILED,
    LlmTaskStatus.TIMEOUT,
    LlmTaskStatus.CANCELED,
}
FIRST_PASS_GOAL = 0.95
POST_REPAIR_GOAL = 0.80
TERMINAL_FAILURE_SHARE_MAX = 0.10
PRIORITY_BAND_1_MAX = 49
PRIORITY_BAND_2_MAX = 99
PRIORITY_BAND_3_MAX = 199


@dataclass(slots=True)
class RetryClassMetric:
    """Retry metrics for one failure class."""

    failure_class: str
    scheduled: int
    succeeded_after_retry: int

    @property
    def success_ratio(self) -> float:
        """Retry success ratio for this failure class."""

        if self.scheduled == 0:
            return 0.0
        return self.succeeded_after_retry / self.scheduled


@dataclass(slots=True)
class LatencyPercentiles:
    """Latency percentiles for one task type."""

    sample_size: int
    p50_seconds: float
    p90_seconds: float
    p99_seconds: float


@dataclass(slots=True)
class OrchestratorMetricsSnapshot:
    """Aggregated orchestrator metrics used by stats/report commands."""

    active_status_counts: dict[str, int]
    active_type_status_counts: dict[str, dict[str, int]]
    queued_priority_bands: dict[str, int]
    window_task_count: int
    terminal_status_counts: dict[str, int]
    validation_failure_counts: dict[str, int]
    first_pass_validation_total: int
    first_pass_schema_valid_rate: float | None
    first_pass_source_mapping_pass_rate: float | None
    repair_attempted_total: int
    repair_success_total: int
    post_repair_success_rate: float | None
    retry_metrics: list[RetryClassMetric]
    failure_class_counts: dict[str, int]
    latency_by_task_type: dict[str, LatencyPercentiles]
    attempt_failure_code_counts: dict[str, int]
    attempt_missing_output_count: int
    attempt_total_count: int
    attempt_repair_success_count: int
    attempt_repair_total_count: int
    attempt_failure_class_counts: dict[str, int]


def build_orchestrator_metrics(  # noqa: C901, PLR0912, PLR0915
    *,
    active_tasks: list[LlmTaskView],
    window_tasks: list[LlmTaskView],
    window_events: list[LlmTaskEventView],
    window_attempts: list[LlmTaskAttemptView] | None = None,
) -> OrchestratorMetricsSnapshot:
    """Build one metrics snapshot from task/event views."""

    active_status_counts = Counter[str]()
    active_type_status_counts = Counter[tuple[str, str]]()
    queued_priority_bands = Counter[str]()

    for task in active_tasks:
        status = task.status.value
        active_status_counts[status] += 1
        active_type_status_counts[(task.task_type, status)] += 1
        if task.status == LlmTaskStatus.QUEUED:
            queued_priority_bands[_priority_band(task.priority)] += 1

    event_by_task: dict[str, list[LlmTaskEventView]] = defaultdict(list)
    for event in window_events:
        event_by_task[event.task_id].append(event)

    first_pass_validation_total = 0
    schema_valid_first_pass = 0
    source_mapping_valid_first_pass = 0
    validation_failure_counts = Counter[str]()

    repair_attempted_total = 0
    repair_success_total = 0

    terminal_status_counts = Counter[str]()
    failure_class_counts = Counter[str]()

    latency_values: dict[str, list[float]] = defaultdict(list)

    final_status_by_task = {task.task_id: task.status for task in window_tasks}

    retry_totals = Counter[str]()
    retry_successes = Counter[str]()
    for event in window_events:
        if event.event_type != "retry_scheduled":
            continue
        failure_class = str(event.details.get("failure_class", "unknown"))
        retry_totals[failure_class] += 1
        if final_status_by_task.get(event.task_id) == LlmTaskStatus.SUCCEEDED:
            retry_successes[failure_class] += 1

    for task in window_tasks:
        events = event_by_task.get(task.task_id, [])
        first_pass_event = next(
            (
                event
                for event in events
                if event.event_type
                in {
                    "first_pass_validation_passed",
                    "first_pass_validation_failed",
                }
            ),
            None,
        )

        if first_pass_event is not None:
            first_pass_validation_total += 1
            if first_pass_event.event_type == "first_pass_validation_passed":
                schema_valid_first_pass += 1
                source_mapping_valid_first_pass += 1
            else:
                failure_class = str(first_pass_event.details.get("failure_class", "unknown"))
                validation_failure_counts[failure_class] += 1
                if failure_class == "source_mapping_failed":
                    schema_valid_first_pass += 1
        elif task.failure_class is not None and task.failure_class.value in {
            "output_invalid_json",
            "source_mapping_failed",
        }:
            validation_failure_counts[task.failure_class.value] += 1

        has_repair = any(event.event_type == "repair_attempted" for event in events)
        if has_repair:
            repair_attempted_total += 1
            if task.status == LlmTaskStatus.SUCCEEDED:
                repair_success_total += 1

        if task.status in _TERMINAL_STATUSES:
            terminal_status_counts[task.status.value] += 1
            if task.failure_class is not None:
                failure_class_counts[task.failure_class.value] += 1
            if task.finished_at is not None:
                latency_seconds = max(
                    0.0,
                    (
                        task.finished_at.astimezone(UTC) - task.created_at.astimezone(UTC)
                    ).total_seconds(),
                )
                latency_values[task.task_type].append(latency_seconds)

    first_pass_schema_valid_rate = _safe_ratio(
        numerator=schema_valid_first_pass,
        denominator=first_pass_validation_total,
    )
    first_pass_source_mapping_pass_rate = _safe_ratio(
        numerator=source_mapping_valid_first_pass,
        denominator=first_pass_validation_total,
    )
    post_repair_success_rate = _safe_ratio(
        numerator=repair_success_total,
        denominator=repair_attempted_total,
    )

    retry_metrics = [
        RetryClassMetric(
            failure_class=failure_class,
            scheduled=count,
            succeeded_after_retry=retry_successes[failure_class],
        )
        for failure_class, count in sorted(retry_totals.items())
    ]

    latency_by_task_type = {
        task_type: LatencyPercentiles(
            sample_size=len(values),
            p50_seconds=_percentile(values, 0.50),
            p90_seconds=_percentile(values, 0.90),
            p99_seconds=_percentile(values, 0.99),
        )
        for task_type, values in sorted(latency_values.items())
    }

    attempt_failure_code_counts = Counter[str]()
    attempt_missing_output_count = 0
    attempt_total_count = 0
    attempt_repair_success_count = 0
    attempt_repair_total_count = 0
    attempt_failure_class_counts = Counter[str]()

    for attempt in window_attempts or []:
        attempt_total_count += 1
        if attempt.attempt_failure_code:
            attempt_failure_code_counts[attempt.attempt_failure_code] += 1
        if attempt.failure_class is not None:
            attempt_failure_class_counts[attempt.failure_class.value] += 1
        if attempt.output_chars is not None and attempt.output_chars == 0:
            attempt_missing_output_count += 1
        if attempt.attempt_failure_code and "repair" in attempt.attempt_failure_code:
            attempt_repair_total_count += 1
            if attempt.status == "succeeded":
                attempt_repair_success_count += 1

    return OrchestratorMetricsSnapshot(
        active_status_counts=dict(sorted(active_status_counts.items())),
        active_type_status_counts=_sorted_nested_counter(active_type_status_counts),
        queued_priority_bands={
            band: queued_priority_bands[band]
            for band in ("0-49", "50-99", "100-199", "200+")
            if band in queued_priority_bands
        },
        window_task_count=len(window_tasks),
        terminal_status_counts=dict(sorted(terminal_status_counts.items())),
        validation_failure_counts={
            key: validation_failure_counts.get(key, 0)
            for key in ("output_invalid_json", "source_mapping_failed")
        },
        first_pass_validation_total=first_pass_validation_total,
        first_pass_schema_valid_rate=first_pass_schema_valid_rate,
        first_pass_source_mapping_pass_rate=first_pass_source_mapping_pass_rate,
        repair_attempted_total=repair_attempted_total,
        repair_success_total=repair_success_total,
        post_repair_success_rate=post_repair_success_rate,
        retry_metrics=retry_metrics,
        failure_class_counts=dict(sorted(failure_class_counts.items())),
        latency_by_task_type=latency_by_task_type,
        attempt_failure_code_counts=dict(sorted(attempt_failure_code_counts.items())),
        attempt_missing_output_count=attempt_missing_output_count,
        attempt_total_count=attempt_total_count,
        attempt_repair_success_count=attempt_repair_success_count,
        attempt_repair_total_count=attempt_repair_total_count,
        attempt_failure_class_counts=dict(sorted(attempt_failure_class_counts.items())),
    )


def render_stats_lines(*, snapshot: OrchestratorMetricsSnapshot, hours: int) -> list[str]:
    """Render operator-facing metrics lines for CLI output."""

    lines = [
        f"LLM queue health (window={hours}h)",
        (
            "Queue status: "
            + (_fmt_key_value(snapshot.active_status_counts) or "queued=0 running=0")
        ),
        ("Queue type/status: " + (_fmt_type_status(snapshot.active_type_status_counts) or "none")),
        ("Queued priority bands: " + (_fmt_key_value(snapshot.queued_priority_bands) or "none")),
        f"Window tasks: {snapshot.window_task_count}",
        (
            "Terminal status distribution: "
            + (_fmt_key_value(snapshot.terminal_status_counts) or "none")
        ),
        (
            "Validation failures: "
            f"output_invalid_json={snapshot.validation_failure_counts['output_invalid_json']} "
            f"source_mapping_failed={snapshot.validation_failure_counts['source_mapping_failed']}"
        ),
        (
            "First-pass validation: "
            f"checked={snapshot.first_pass_validation_total} "
            f"schema_valid_rate={_fmt_ratio(snapshot.first_pass_schema_valid_rate)} "
            "strict_source_mapping_pass_rate="
            f"{_fmt_ratio(snapshot.first_pass_source_mapping_pass_rate)}"
        ),
        (
            "Post-repair success: "
            f"repaired={snapshot.repair_attempted_total} "
            f"succeeded={snapshot.repair_success_total} "
            f"rate={_fmt_ratio(snapshot.post_repair_success_rate)}"
        ),
    ]

    if snapshot.retry_metrics:
        lines.append("Retry metrics:")
        for metric in snapshot.retry_metrics:
            lines.append(
                "  "
                f"failure_class={metric.failure_class} scheduled={metric.scheduled} "
                f"succeeded_after_retry={metric.succeeded_after_retry} "
                f"success_ratio={_fmt_ratio(metric.success_ratio)}",
            )
    else:
        lines.append("Retry metrics: none")

    if snapshot.failure_class_counts:
        lines.append(
            "Failure-class distribution: " + _fmt_key_value(snapshot.failure_class_counts),
        )
    else:
        lines.append("Failure-class distribution: none")

    if snapshot.latency_by_task_type:
        lines.append("Latency percentiles (created_at -> finished_at):")
        for task_type, metrics in snapshot.latency_by_task_type.items():
            lines.append(
                "  "
                f"task_type={task_type} n={metrics.sample_size} "
                f"p50={metrics.p50_seconds:.2f}s "
                f"p90={metrics.p90_seconds:.2f}s "
                f"p99={metrics.p99_seconds:.2f}s",
            )
    else:
        lines.append("Latency percentiles: none")

    if snapshot.attempt_total_count > 0:
        missing_output_rate = snapshot.attempt_missing_output_count / snapshot.attempt_total_count
        repair_rate = (
            snapshot.attempt_repair_success_count / snapshot.attempt_repair_total_count
            if snapshot.attempt_repair_total_count > 0
            else None
        )
        lines.append(
            f"Attempt-level metrics: total={snapshot.attempt_total_count} "
            f"missing_output_rate={missing_output_rate:.2%} "
            f"repair_success_rate={_fmt_ratio(repair_rate)}",
        )
        if snapshot.attempt_failure_code_counts:
            lines.append(
                "Attempt failure codes: " + _fmt_key_value(snapshot.attempt_failure_code_counts),
            )
        if snapshot.attempt_failure_class_counts:
            lines.append(
                "Attempt failure-class distribution: "
                + _fmt_key_value(snapshot.attempt_failure_class_counts),
            )
    else:
        lines.append("Attempt-level metrics: none")

    return lines


def render_benchmark_report(
    *,
    snapshot: OrchestratorMetricsSnapshot,
    generated_at: datetime,
    task_types: tuple[str, ...],
    benchmark_command: str,
) -> str:
    """Render benchmark report markdown with go/no-go recommendation."""

    verdict, reasons = evaluate_go_no_go(snapshot=snapshot, task_types=task_types)
    latency_lines = [
        (
            f"- `{task_type}`: n={metrics.sample_size}, "
            f"p50={metrics.p50_seconds:.2f}s, "
            f"p90={metrics.p90_seconds:.2f}s, "
            f"p99={metrics.p99_seconds:.2f}s"
        )
        for task_type, metrics in snapshot.latency_by_task_type.items()
    ]
    if not latency_lines:
        latency_lines = ["- none"]

    retry_lines = [
        (
            f"- `{metric.failure_class}`: scheduled={metric.scheduled}, "
            f"succeeded_after_retry={metric.succeeded_after_retry}, "
            f"success_ratio={_fmt_ratio(metric.success_ratio)}"
        )
        for metric in snapshot.retry_metrics
    ]
    if not retry_lines:
        retry_lines = ["- none"]

    reason_lines = [f"- {reason}" for reason in reasons] or ["- none"]

    return "\n".join(
        [
            "# Epic 2 Benchmark Report",
            "",
            f"Generated at: `{generated_at.astimezone(UTC).isoformat()}`",
            f"Task types: `{', '.join(task_types)}`",
            f"Window task count: `{snapshot.window_task_count}`",
            "",
            "## Reproducible Command",
            "",
            "```bash",
            benchmark_command,
            "```",
            "",
            "## Core Metrics",
            "",
            "- First-pass schema validity rate: "
            f"`{_fmt_ratio(snapshot.first_pass_schema_valid_rate)}` "
            f"(checked={snapshot.first_pass_validation_total})",
            "- First-pass strict source-mapping pass rate: "
            f"`{_fmt_ratio(snapshot.first_pass_source_mapping_pass_rate)}`",
            "- Post-repair success rate: "
            f"`{_fmt_ratio(snapshot.post_repair_success_rate)}` "
            f"(repaired={snapshot.repair_attempted_total}, "
            f"succeeded={snapshot.repair_success_total})",
            "- Terminal status distribution: "
            f"`{_fmt_key_value(snapshot.terminal_status_counts) or 'none'}`",
            "- Validation failure counters: "
            f"`output_invalid_json={snapshot.validation_failure_counts['output_invalid_json']}` "
            f"`source_mapping_failed={snapshot.validation_failure_counts['source_mapping_failed']}`",
            "",
            "### Retry Metrics",
            *retry_lines,
            "",
            "### Failure-Class Distribution",
            f"- {_fmt_key_value(snapshot.failure_class_counts) or 'none'}",
            "",
            "### Latency Percentiles By Task Type",
            *latency_lines,
            "",
            "## Recommendation",
            "",
            f"Go/No-Go recommendation: **{verdict}**",
            "",
            "Rationale:",
            *reason_lines,
            "",
        ],
    )


def evaluate_go_no_go(
    *,
    snapshot: OrchestratorMetricsSnapshot,
    task_types: tuple[str, ...],
) -> tuple[str, list[str]]:
    """Compute deterministic benchmark recommendation."""

    reasons: list[str] = []

    observed_types = set(snapshot.latency_by_task_type)
    missing_types = [task_type for task_type in task_types if task_type not in observed_types]
    if missing_types:
        reasons.append(
            "Benchmark matrix missing terminal samples for task types: "
            f"{', '.join(missing_types)}.",
        )

    if snapshot.first_pass_source_mapping_pass_rate is None:
        reasons.append("No first-pass validation samples were captured.")
    elif snapshot.first_pass_source_mapping_pass_rate < FIRST_PASS_GOAL:
        reasons.append(
            "First-pass strict source-mapping pass rate is below 95% "
            f"({snapshot.first_pass_source_mapping_pass_rate:.2%}).",
        )

    if snapshot.first_pass_schema_valid_rate is None:
        reasons.append("No first-pass schema validation samples were captured.")
    elif snapshot.first_pass_schema_valid_rate < FIRST_PASS_GOAL:
        reasons.append(
            "First-pass schema validity rate is below 95% "
            f"({snapshot.first_pass_schema_valid_rate:.2%}).",
        )

    if (
        snapshot.post_repair_success_rate is not None
        and snapshot.post_repair_success_rate < POST_REPAIR_GOAL
    ):
        reasons.append(
            f"Post-repair success rate is below 80% ({snapshot.post_repair_success_rate:.2%}).",
        )

    terminal_total = sum(snapshot.terminal_status_counts.values())
    bad_terminal = snapshot.terminal_status_counts.get(
        "failed",
        0,
    ) + snapshot.terminal_status_counts.get(
        "timeout",
        0,
    )
    bad_ratio = _safe_ratio(numerator=bad_terminal, denominator=terminal_total)
    if bad_ratio is not None and bad_ratio > TERMINAL_FAILURE_SHARE_MAX:
        reasons.append(
            f"Failed+timeout share among terminal tasks is above 10% ({bad_ratio:.2%}).",
        )

    if reasons:
        return "NO-GO", reasons
    return "GO", ["All Epic 2 benchmark gates passed."]


def _priority_band(priority: int) -> str:
    if priority <= PRIORITY_BAND_1_MAX:
        return "0-49"
    if priority <= PRIORITY_BAND_2_MAX:
        return "50-99"
    if priority <= PRIORITY_BAND_3_MAX:
        return "100-199"
    return "200+"


def _safe_ratio(*, numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _fmt_key_value(values: dict[str, int]) -> str:
    if not values:
        return ""
    return " ".join(f"{key}={values[key]}" for key in sorted(values))


def _fmt_type_status(values: dict[str, dict[str, int]]) -> str:
    if not values:
        return ""
    flattened: list[str] = []
    for task_type in sorted(values):
        for status in sorted(values[task_type]):
            flattened.append(f"{task_type}/{status}={values[task_type][status]}")
    return " ".join(flattened)


def _sorted_nested_counter(counter: Counter[tuple[str, str]]) -> dict[str, dict[str, int]]:
    nested: dict[str, dict[str, int]] = defaultdict(dict)
    for (task_type, status), count in counter.items():
        nested[task_type][status] = count
    return {
        task_type: dict(sorted(statuses.items())) for task_type, statuses in sorted(nested.items())
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
