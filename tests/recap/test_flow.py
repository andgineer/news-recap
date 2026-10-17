from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from news_recap.recap.exceptions import RecapPipelineError
from news_recap.recap.flow import _log_pipeline_token_summary, recap_flow
from news_recap.recap.models import Digest
from news_recap.recap.tasks.classify import Classify


def _write_usage(task_dir: Path, *, tokens: int) -> None:
    path = task_dir / "meta" / "usage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "elapsed_seconds": 1.0,
                "tokens_used": tokens,
                "total_tokens": tokens,
            }
        ),
        encoding="utf-8",
    )


def test_log_token_summary_aggregates_phases(tmp_path: Path) -> None:
    _write_usage(tmp_path / "classify-1", tokens=400)
    _write_usage(tmp_path / "classify-2", tokens=600)
    mock_logger = MagicMock()
    _log_pipeline_token_summary(mock_logger, tmp_path)
    mock_logger.info.assert_called_once()
    args = mock_logger.info.call_args[0]
    assert (args[0] % args[1:]).endswith("classify=1,000 | total=1,000")


def test_log_token_summary_lists_jev_apart_from_the_total(tmp_path: Path) -> None:
    _write_usage(tmp_path / "enrich-1", tokens=300)
    _write_usage(tmp_path / "dedup-jev", tokens=5_000)
    mock_logger = MagicMock()
    _log_pipeline_token_summary(mock_logger, tmp_path)
    args = mock_logger.info.call_args[0]
    assert (args[0] % args[1:]).endswith("enrich=300 | total=300 | dedup-jev=5,000")


def test_log_token_summary_skips_zero_tokens(tmp_path: Path) -> None:
    _write_usage(tmp_path / "classify-1", tokens=0)
    mock_logger = MagicMock()
    _log_pipeline_token_summary(mock_logger, tmp_path)
    mock_logger.info.assert_not_called()


def test_log_token_summary_empty_dir(tmp_path: Path) -> None:
    mock_logger = MagicMock()
    _log_pipeline_token_summary(mock_logger, tmp_path)
    mock_logger.info.assert_not_called()


def _fail_run(tmp_path: Path, first_step) -> Digest:
    inp = MagicMock(articles=[], coverage_start=None, coverage_end=None, selection_params=None)
    inp.routing_defaults.execution_backend = "cli"
    with (
        patch("news_recap.recap.flow.read_pipeline_input", return_value=inp),
        patch.object(Classify, "run", side_effect=first_step),
        patch("news_recap.recap.flow.finalize_digest_entry") as finalize,
    ):
        recap_flow(str(tmp_path), "2026-10-17")
    return finalize.call_args.args[2]


def test_failed_run_records_the_failing_steps_batch_error(tmp_path: Path) -> None:
    def fail(ctx) -> None:
        ctx.batch_errors["recap_dedup"] = "Step recap_dedup failed: tolerated earlier"
        ctx.batch_errors["recap_enrich"] = "Step recap_enrich failed: antigravity: Invalid model"
        raise RecapPipelineError("recap_enrich", "batch failed (0/3 enriched) — see errors above")

    digest = _fail_run(tmp_path, fail)
    assert digest.status == "failed"
    assert digest.error == "Step recap_enrich failed: antigravity: Invalid model"


def test_failed_run_without_batch_error_records_the_step_error(tmp_path: Path) -> None:
    def fail(_ctx) -> None:
        raise RecapPipelineError("recap_oneshot_digest", "coverage too low")

    digest = _fail_run(tmp_path, fail)
    assert digest.error == "Step recap_oneshot_digest failed: coverage too low"


def test_unexpected_error_is_recorded(tmp_path: Path) -> None:
    def fail(_ctx) -> None:
        raise ValueError("bad json")

    assert _fail_run(tmp_path, fail).error == "Unexpected error: ValueError: bad json"
