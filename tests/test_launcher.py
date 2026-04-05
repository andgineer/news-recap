"""Tests for launcher helpers."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec

from news_recap.recap.launcher import (
    RecapCliController,
    RecapRunCommand,
    _load_from_pipeline,
    _patch_pipeline_input,
)
from news_recap.recap.models import Digest, DigestArticle
from news_recap.recap.storage.pipeline_io import read_pipeline_input

_TODAY = datetime.now(tz=UTC).date()


def _write_pipeline_input(
    tmp_path: Path,
    agent_override: str | None = "codex",
    run_date: date | None = None,
) -> None:
    bdate = run_date or _TODAY
    payload = {
        "run_date": bdate.isoformat(),
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


def _write_digest(
    pipeline_dir: Path,
    completed_phases: list[str] | None = None,
    run_date: date | None = None,
    status: str = "in_progress",
) -> None:
    bdate = run_date or _TODAY
    digest = Digest(
        digest_id="test-digest",
        run_date=bdate.isoformat(),
        status=status,
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
    pipeline_dir = workdir_root / f"pipeline-{_TODAY}-120000"
    pipeline_dir.mkdir(parents=True)
    _write_pipeline_input(pipeline_dir, agent_override="codex")
    _write_digest(pipeline_dir, completed_phases=["triage"])

    settings = MagicMock()
    settings.data_dir = tmp_path / "data"
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
        agent_override="Claude",
    )

    messages = [text for _, text in RecapCliController().run_pipeline(command)]

    assert any("Agent override changed: codex -> claude" in m for m in messages)
    assert not any("Claude" in m for m in messages), "raw CLI value should not appear in output"

    inp = read_pipeline_input(str(pipeline_dir))
    assert inp.agent_override == "claude"


# ---------------------------------------------------------------------------
# _load_from_pipeline
# ---------------------------------------------------------------------------

_SOURCE_DATE = date(2026, 3, 25)


_SOURCE_DIGEST_ID = 1
_SOURCE_DIR_NAME = "pipeline-2026-03-25-080307"


def _make_source_pipeline(
    tmp_path: Path, n_articles: int = 3, *, workdir_root: Path | None = None
) -> Path:
    """Create a fake source pipeline dir with *n_articles* articles and a digest index."""
    root = workdir_root or tmp_path
    source_dir = root / _SOURCE_DIR_NAME
    source_dir.mkdir(parents=True, exist_ok=True)
    articles = [
        msgspec.structs.asdict(
            DigestArticle(
                article_id=f"art-{i}",
                title=f"Title {i}",
                url=f"https://example.com/{i}",
                source="test-feed",
                published_at="2026-03-25T00:00:00Z",
                clean_text=f"body {i}",
            )
        )
        for i in range(n_articles)
    ]
    payload = {
        "run_date": _SOURCE_DATE.isoformat(),
        "articles": articles,
        "preferences": {"max_headline_chars": 120, "language": "ru"},
        "routing_defaults": {
            "default_agent": "codex",
            "task_model_map": {},
            "command_templates": {},
            "task_type_timeout_map": {},
        },
        "agent_override": "codex",
        "data_dir": str(tmp_path),
    }
    (source_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False), "utf-8"
    )
    index = [
        {
            "digest_id": _SOURCE_DIGEST_ID,
            "pipeline_dir_name": _SOURCE_DIR_NAME,
            "run_date": _SOURCE_DATE.isoformat(),
            "article_count": n_articles,
        }
    ]
    (root / "digests.json").write_text(json.dumps(index), "utf-8")
    return source_dir


def test_load_from_pipeline_returns_date_and_articles(tmp_path: Path) -> None:
    source_dir = _make_source_pipeline(tmp_path, n_articles=5)

    bdate, articles = _load_from_pipeline(source_dir)

    assert bdate == _SOURCE_DATE
    assert len(articles) == 5
    assert all(isinstance(a, DigestArticle) for a in articles)
    assert articles[0].article_id == "art-0"


def test_load_from_pipeline_missing_file(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        _load_from_pipeline(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# --from-digest through the controller
# ---------------------------------------------------------------------------


def _make_settings_mock(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.orchestrator.workdir_root = tmp_path / "workdirs"
    settings.orchestrator.default_agent = "codex"
    settings.orchestrator.task_model_map = {}
    settings.orchestrator.claude_command_template = ""
    settings.orchestrator.codex_command_template = ""
    settings.orchestrator.gemini_command_template = ""
    settings.orchestrator.task_type_timeout_map = {}
    settings.orchestrator.agent_max_parallel = {}
    settings.orchestrator.agent_launch_delay = {}
    settings.orchestrator.execution_backend = "cli"
    settings.orchestrator.api_model_map = {}
    settings.orchestrator.api_max_parallel = 4
    settings.orchestrator.api_concurrency_recovery_successes = 3
    settings.orchestrator.api_downshift_pause_seconds = 5.0
    settings.orchestrator.api_retry_max_backoff_seconds = 60.0
    settings.orchestrator.api_retry_jitter_seconds = 1.0
    settings.orchestrator.agent_api_key_vars = {}
    settings.data_dir = tmp_path / "data"
    settings.ingestion.gc_retention_days = 30
    settings.ingestion.digest_lookback_days = 7
    settings.ingestion.min_resource_chars = 200
    settings.dedup.threshold = 0.90
    settings.dedup.model_name = "intfloat/multilingual-e5-small"
    return settings


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_from_digest_reuses_articles_and_date(
    mock_from_env: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """--from-digest loads articles and date from the source pipeline."""
    settings = _make_settings_mock(tmp_path)
    mock_from_env.return_value = settings
    workdir_root = settings.orchestrator.workdir_root
    workdir_root.mkdir(parents=True, exist_ok=True)
    _make_source_pipeline(tmp_path, n_articles=7, workdir_root=workdir_root)

    command = RecapRunCommand(
        from_digest=_SOURCE_DIGEST_ID,
        agent_override="claude",
    )

    messages = [text for _, text in RecapCliController().run_pipeline(command)]

    assert any("Reusing 7" in m for m in messages)
    assert any("2026-03-25" in m for m in messages)

    mock_flow.assert_called_once()
    call_kwargs = mock_flow.call_args
    assert call_kwargs[1]["run_date"] == "2026-03-25"

    new_pipeline_dir = Path(call_kwargs[1]["pipeline_dir"])
    new_inp = read_pipeline_input(str(new_pipeline_dir))
    assert len(new_inp.articles) == 7
    assert new_inp.agent_override == "claude"
    assert new_inp.run_date == _SOURCE_DATE.isoformat()


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_from_digest_applies_new_options(
    mock_from_env: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """New options (agent, use_api_key) override source pipeline values."""
    settings = _make_settings_mock(tmp_path)
    mock_from_env.return_value = settings
    workdir_root = settings.orchestrator.workdir_root
    workdir_root.mkdir(parents=True, exist_ok=True)
    _make_source_pipeline(tmp_path, n_articles=3, workdir_root=workdir_root)

    command = RecapRunCommand(
        from_digest=_SOURCE_DIGEST_ID,
        agent_override="gemini",
        use_api_key=True,
    )

    list(RecapCliController().run_pipeline(command))

    new_pipeline_dir = Path(mock_flow.call_args[1]["pipeline_dir"])
    new_inp = read_pipeline_input(str(new_pipeline_dir))
    assert new_inp.agent_override == "gemini"
    assert new_inp.use_api_key is True


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_from_digest_skips_resume_logic(
    mock_from_env: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """--from-digest always creates a new pipeline, even if a resumable one exists."""
    settings = _make_settings_mock(tmp_path)
    mock_from_env.return_value = settings
    workdir_root = settings.orchestrator.workdir_root
    workdir_root.mkdir(parents=True, exist_ok=True)
    _make_source_pipeline(tmp_path, n_articles=2, workdir_root=workdir_root)

    resumable_dir = workdir_root / f"pipeline-{_SOURCE_DATE}-120000"
    resumable_dir.mkdir(parents=True)
    _write_pipeline_input(resumable_dir)
    _write_digest(resumable_dir, completed_phases=["classify"])

    command = RecapRunCommand(
        from_digest=_SOURCE_DIGEST_ID,
    )

    messages = [text for _, text in RecapCliController().run_pipeline(command)]

    assert not any("Resuming" in m for m in messages)
    assert any("Reusing 2" in m for m in messages)
