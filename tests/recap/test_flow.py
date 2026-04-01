from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from news_recap.recap.flow import _log_pipeline_token_summary


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
    assert args[-1] == "1,000"


def test_log_token_summary_skips_zero_tokens(tmp_path: Path) -> None:
    _write_usage(tmp_path / "classify-1", tokens=0)
    mock_logger = MagicMock()
    _log_pipeline_token_summary(mock_logger, tmp_path)
    mock_logger.info.assert_not_called()


def test_log_token_summary_empty_dir(tmp_path: Path) -> None:
    mock_logger = MagicMock()
    _log_pipeline_token_summary(mock_logger, tmp_path)
    mock_logger.info.assert_not_called()
