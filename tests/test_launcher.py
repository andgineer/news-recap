"""Tests for launcher helpers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec

from news_recap.recap.launcher import (
    RecapCliController,
    RecapRunCommand,
    _patch_pipeline_input,
)
from news_recap.recap.models import Digest
from news_recap.recap.storage.pipeline_io import read_pipeline_input

_BUSINESS_DATE = date(2026, 2, 19)


def _write_pipeline_input(tmp_path: Path, agent_override: str | None = "codex") -> None:
    payload = {
        "business_date": _BUSINESS_DATE.isoformat(),
        "articles": [],
        "preferences": {"max_headline_chars": 120, "language": "ru"},
        "routing_defaults": {
            "default_agent": "codex",
            "task_model_map": {},
            "command_templates": {},
            "task_type_timeout_map": {},
        },
        "agent_override": agent_override,
        "data_dir": str(tmp_path),
    }
    (tmp_path / "pipeline_input.json").write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def _write_digest(pipeline_dir: Path, completed_phases: list[str] | None = None) -> None:
    digest = Digest(
        digest_id="test-digest",
        business_date=_BUSINESS_DATE.isoformat(),
        status="in_progress",
        pipeline_dir=str(pipeline_dir),
        articles=[],
        completed_phases=completed_phases or [],
    )
    (pipeline_dir / "digest.json").write_bytes(msgspec.json.encode(digest))


def test_patch_pipeline_input_agent_override(tmp_path: Path) -> None:
    """Patched agent_override is normalized and read back correctly."""
    _write_pipeline_input(tmp_path, agent_override="codex")

    previous = _patch_pipeline_input(tmp_path, agent_override="claude")

    assert previous["agent_override"] == "codex"

    inp = read_pipeline_input(str(tmp_path))
    assert inp.agent_override == "claude"


def test_patch_pipeline_input_when_previously_none(tmp_path: Path) -> None:
    """Patching works when the original value is None (default agent)."""
    _write_pipeline_input(tmp_path, agent_override=None)

    previous = _patch_pipeline_input(tmp_path, agent_override="gemini")

    assert previous["agent_override"] is None

    inp = read_pipeline_input(str(tmp_path))
    assert inp.agent_override == "gemini"


def test_patch_pipeline_input_single_pass(tmp_path: Path) -> None:
    """Patching single_pass updates pipeline_input.json."""
    _write_pipeline_input(tmp_path, agent_override=None)

    previous = _patch_pipeline_input(tmp_path, single_pass=True)

    assert previous["single_pass"] is None  # was absent

    inp = read_pipeline_input(str(tmp_path))
    assert inp.single_pass is True


def test_no_agent_flag_leaves_file_unchanged(tmp_path: Path) -> None:
    """Without --agent on resume, agent_override stays as-is."""
    _write_pipeline_input(tmp_path, agent_override="codex")

    inp = read_pipeline_input(str(tmp_path))
    assert inp.agent_override == "codex"


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_controller_resume_with_agent_override_normalizes(
    mock_from_env: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """Controller resume path normalizes agent_override and logs the normalized name."""
    workdir_root = tmp_path / "workdirs"
    pipeline_dir = workdir_root / f"pipeline-{_BUSINESS_DATE}-120000"
    pipeline_dir.mkdir(parents=True)
    _write_pipeline_input(pipeline_dir, agent_override="codex")
    _write_digest(pipeline_dir, completed_phases=["triage"])

    settings = MagicMock()
    settings.orchestrator.workdir_root = workdir_root
    settings.orchestrator.default_agent = "codex"
    settings.orchestrator.task_model_map = {}
    settings.orchestrator.claude_command_template = ""
    settings.orchestrator.codex_command_template = ""
    settings.orchestrator.gemini_command_template = ""
    settings.orchestrator.task_type_timeout_map = {}
    settings.orchestrator.agent_max_parallel = {}
    settings.ingestion.gc_retention_days = 30
    settings.ingestion.digest_lookback_days = 7
    mock_from_env.return_value = settings

    command = RecapRunCommand(
        data_dir=tmp_path,
        business_date=_BUSINESS_DATE,
        agent_override="Claude",
    )

    messages = list(RecapCliController().run_pipeline(command))

    assert any("Agent override changed: codex -> claude" in m for m in messages)
    assert not any("Claude" in m for m in messages), "raw CLI value should not appear in output"

    inp = read_pipeline_input(str(pipeline_dir))
    assert inp.agent_override == "claude"
