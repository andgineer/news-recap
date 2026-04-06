"""Tests for --from/--to date filtering, DateOrDateTime, validation, resume logic."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import msgspec
import pytest

from news_recap.main import DateOrDateTime
from conftest import make_settings_mock
from news_recap.recap.export_prompt import PromptCommand, _selection_params_for_prompt
from news_recap.recap.launcher import (
    RecapCliController,
    RecapRunCommand,
    _find_matching_resumable,
    _selection_params_for_create,
    _serialize_bound,
    _validate_date_filters,
)
from news_recap.recap.models import Digest, DigestArticle
from news_recap.recap.pipeline_setup import _effective_to, _filter_articles_before
from news_recap.recap.storage.pipeline_io import read_pipeline_input

_TODAY = datetime.now(tz=UTC).date()


# ---------------------------------------------------------------------------
# DateOrDateTime
# ---------------------------------------------------------------------------


class TestDateOrDateTime:
    param_type = DateOrDateTime()

    def test_date_only_returns_date(self) -> None:
        result = self.param_type.convert("2026-04-01", None, None)
        assert type(result) is date
        assert result == date(2026, 4, 1)

    def test_datetime_returns_datetime_utc(self) -> None:
        result = self.param_type.convert("2026-04-01T14:30", None, None)
        assert type(result) is datetime
        assert result == datetime(2026, 4, 1, 14, 30, tzinfo=UTC)

    def test_passthrough_date(self) -> None:
        d = date(2026, 1, 1)
        assert self.param_type.convert(d, None, None) is d

    def test_passthrough_datetime(self) -> None:
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert self.param_type.convert(dt, None, None) is dt

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(Exception):
            self.param_type.convert("not-a-date", None, None)


# ---------------------------------------------------------------------------
# _serialize_bound
# ---------------------------------------------------------------------------


class TestSerializeBound:
    def test_none(self) -> None:
        assert _serialize_bound(None) is None

    def test_date(self) -> None:
        assert _serialize_bound(date(2026, 4, 1)) == {
            "kind": "date",
            "value": "2026-04-01",
        }

    def test_datetime(self) -> None:
        dt = datetime(2026, 4, 1, 14, 30, tzinfo=UTC)
        result = _serialize_bound(dt)
        assert result["kind"] == "datetime"
        assert "2026-04-01" in result["value"]
        assert "14:30" in result["value"]

    def test_stable_equality(self) -> None:
        dt = datetime(2026, 4, 1, 14, 30, tzinfo=UTC)
        assert _serialize_bound(dt) == _serialize_bound(dt)

    def test_date_vs_datetime_differ(self) -> None:
        d = date(2026, 4, 1)
        dt = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        assert _serialize_bound(d) != _serialize_bound(dt)


# ---------------------------------------------------------------------------
# _selection_params_for_create / _selection_params_for_prompt
# ---------------------------------------------------------------------------


class TestSelectionParams:
    def test_create_default_command(self) -> None:
        cmd = RecapRunCommand()
        params = _selection_params_for_create(cmd)
        assert params["article_limit"] is None
        assert params["from_digest"] is None
        assert params["date_from"] is None
        assert params["date_to"] is None

    def test_create_with_date_from(self) -> None:
        cmd = RecapRunCommand(date_from=date(2026, 4, 1))
        params = _selection_params_for_create(cmd)
        assert params["date_from"] == {"kind": "date", "value": "2026-04-01"}
        assert params["date_to"] is None

    def test_prompt_default_command(self) -> None:
        cmd = PromptCommand()
        params = _selection_params_for_prompt(cmd)
        assert params["date_from"] is None
        assert params["date_to"] is None
        assert "ai" not in params

    def test_prompt_with_dates(self) -> None:
        dt = datetime(2026, 4, 1, 14, 0, tzinfo=UTC)
        cmd = PromptCommand(date_from=dt, date_to=date(2026, 4, 3))
        params = _selection_params_for_prompt(cmd)
        assert params["date_from"]["kind"] == "datetime"
        assert params["date_to"]["kind"] == "date"


# ---------------------------------------------------------------------------
# _validate_date_filters
# ---------------------------------------------------------------------------


class TestValidateDateFilters:
    def test_no_dates_is_ok(self) -> None:
        _validate_date_filters(None, None, None, None, False)

    def test_from_only_is_ok(self) -> None:
        _validate_date_filters(date(2026, 4, 1), None, None, None, False)

    def test_to_only_is_ok(self) -> None:
        _validate_date_filters(None, date(2026, 4, 3), None, None, False)

    def test_from_and_to_valid(self) -> None:
        _validate_date_filters(
            date(2026, 4, 1),
            date(2026, 4, 3),
            None,
            None,
            False,
        )

    def test_from_after_to_raises(self) -> None:
        with pytest.raises(Exception, match="--from must be before --to"):
            _validate_date_filters(
                date(2026, 4, 5),
                date(2026, 4, 3),
                None,
                None,
                False,
            )

    def test_same_date_is_valid(self) -> None:
        """--from 2026-04-03 --to 2026-04-03 selects the full day (midnight..next midnight)."""
        _validate_date_filters(
            date(2026, 4, 3),
            date(2026, 4, 3),
            None,
            None,
            False,
        )

    def test_datetime_from_after_date_to_raises(self) -> None:
        with pytest.raises(Exception, match="--from must be before --to"):
            _validate_date_filters(
                datetime(2026, 4, 4, 0, 1, tzinfo=UTC),
                date(2026, 4, 3),
                None,
                None,
                False,
            )

    def test_from_with_from_digest_raises(self) -> None:
        with pytest.raises(Exception, match="--from-digest"):
            _validate_date_filters(date(2026, 4, 1), None, 1, None, False)

    def test_to_with_from_digest_raises(self) -> None:
        with pytest.raises(Exception, match="--from-digest"):
            _validate_date_filters(None, date(2026, 4, 3), 1, None, False)

    def test_from_with_max_days_raises(self) -> None:
        with pytest.raises(Exception, match="--max-days"):
            _validate_date_filters(date(2026, 4, 1), None, None, 5, False)

    def test_to_with_all_raises(self) -> None:
        with pytest.raises(Exception, match="--all"):
            _validate_date_filters(None, date(2026, 4, 3), None, None, True)


# ---------------------------------------------------------------------------
# _filter_articles_before
# ---------------------------------------------------------------------------


def _make_article(published_at: str) -> DigestArticle:
    return DigestArticle(
        article_id="a1",
        title="T",
        url="https://example.com",
        source="s",
        published_at=published_at,
        clean_text="body",
    )


class TestFilterArticlesBefore:
    def test_date_includes_full_day(self) -> None:
        articles = [
            _make_article("2026-04-01T00:00:00+00:00"),
            _make_article("2026-04-01T23:59:59+00:00"),
            _make_article("2026-04-02T00:00:01+00:00"),
        ]
        result = _filter_articles_before(articles, date(2026, 4, 1))
        assert len(result) == 2

    def test_datetime_inclusive(self) -> None:
        articles = [
            _make_article("2026-04-01T14:30:00+00:00"),
            _make_article("2026-04-01T14:30:01+00:00"),
        ]
        cutoff = datetime(2026, 4, 1, 14, 30, 0, tzinfo=UTC)
        result = _filter_articles_before(articles, cutoff)
        assert len(result) == 1

    def test_empty_list(self) -> None:
        assert _filter_articles_before([], date(2026, 4, 1)) == []


# ---------------------------------------------------------------------------
# _find_matching_resumable
# ---------------------------------------------------------------------------


def _write_pipeline(
    pdir: Path,
    *,
    status: str = "in_progress",
    completed_phases: list[str] | None = None,
    selection_params: dict | None = None,
) -> None:
    pdir.mkdir(parents=True, exist_ok=True)
    digest = Digest(
        digest_id="d",
        run_date=_TODAY.isoformat(),
        status=status,
        pipeline_dir=str(pdir),
        articles=[],
        completed_phases=completed_phases or [],
    )
    (pdir / "digest.json").write_bytes(msgspec.json.encode(digest))

    payload: dict = {
        "run_date": _TODAY.isoformat(),
        "articles": [],
        "preferences": {"max_headline_chars": 120, "language": "ru"},
        "routing_defaults": {
            "default_agent": "codex",
            "task_model_map": {},
            "command_templates": {},
            "task_type_timeout_map": {},
        },
        "agent_override": None,
        "data_dir": str(pdir.parent),
    }
    if selection_params is not None:
        payload["selection_params"] = selection_params
    (pdir / "pipeline_input.json").write_text(json.dumps(payload), "utf-8")


class TestFindMatchingResumable:
    def test_resumes_matching_params(self, tmp_path: Path) -> None:
        params = _selection_params_for_create(RecapRunCommand())
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, selection_params=params)

        result = _find_matching_resumable(tmp_path, 7, params)
        assert result == pdir

    def test_skips_different_params(self, tmp_path: Path) -> None:
        stored_params = _selection_params_for_create(RecapRunCommand(article_limit=10))
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, selection_params=stored_params)

        current_params = _selection_params_for_create(RecapRunCommand(article_limit=20))
        result = _find_matching_resumable(tmp_path, 7, current_params)
        assert result is None

    def test_skips_legacy_without_selection_params(self, tmp_path: Path) -> None:
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, selection_params=None)

        params = _selection_params_for_create(RecapRunCommand())
        result = _find_matching_resumable(tmp_path, 7, params)
        assert result is None

    def test_skips_completed_pipeline(self, tmp_path: Path) -> None:
        params = _selection_params_for_create(RecapRunCommand())
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, status="completed", selection_params=params)

        result = _find_matching_resumable(tmp_path, 7, params)
        assert result is None

    def test_finds_latest_matching_among_multiple(self, tmp_path: Path) -> None:
        params = _selection_params_for_create(RecapRunCommand())
        old_dir = tmp_path / f"pipeline-{_TODAY}-090000"
        new_dir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(old_dir, selection_params=params)
        _write_pipeline(new_dir, selection_params=params)

        result = _find_matching_resumable(tmp_path, 7, params)
        assert result == new_dir

    def test_scans_past_non_matching_to_find_match(self, tmp_path: Path) -> None:
        match_params = _selection_params_for_create(RecapRunCommand())
        other_params = _selection_params_for_create(RecapRunCommand(article_limit=5))

        older = tmp_path / f"pipeline-{_TODAY}-080000"
        newer = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(older, selection_params=match_params)
        _write_pipeline(newer, selection_params=other_params)

        result = _find_matching_resumable(tmp_path, 7, match_params)
        assert result == older

    def test_scans_past_unrelated_completed(self, tmp_path: Path) -> None:
        """A newer completed pipeline with different params does not block an older match."""
        match_params = _selection_params_for_create(RecapRunCommand())
        other_params = _selection_params_for_create(RecapRunCommand(article_limit=5))

        older_match = tmp_path / f"pipeline-{_TODAY}-080000"
        newer_completed = tmp_path / f"pipeline-{_TODAY}-090000"
        _write_pipeline(older_match, selection_params=match_params)
        _write_pipeline(newer_completed, status="completed", selection_params=other_params)

        result = _find_matching_resumable(tmp_path, 7, match_params)
        assert result == older_match

    def test_empty_workdir(self, tmp_path: Path) -> None:
        params = _selection_params_for_create(RecapRunCommand())
        result = _find_matching_resumable(tmp_path, 7, params)
        assert result is None

    def test_nonexistent_workdir(self, tmp_path: Path) -> None:
        params = _selection_params_for_create(RecapRunCommand())
        result = _find_matching_resumable(tmp_path / "nope", 7, params)
        assert result is None

    def test_resume_with_date_from_match(self, tmp_path: Path) -> None:
        cmd = RecapRunCommand(date_from=date(2026, 4, 1))
        params = _selection_params_for_create(cmd)
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, selection_params=params)

        result = _find_matching_resumable(tmp_path, 30, params)
        assert result == pdir

    def test_resume_date_from_null_to_still_resumes(self, tmp_path: Path) -> None:
        """--from without --to: raw date_to=null resumes correctly."""
        cmd = RecapRunCommand(date_from=date(2026, 4, 1))
        params = _selection_params_for_create(cmd)
        assert params["date_to"] is None
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, selection_params=params)

        result = _find_matching_resumable(tmp_path, 30, params)
        assert result == pdir

    def test_resume_skipped_when_date_from_differs(self, tmp_path: Path) -> None:
        stored = _selection_params_for_create(RecapRunCommand(date_from=date(2026, 4, 1)))
        pdir = tmp_path / f"pipeline-{_TODAY}-100000"
        _write_pipeline(pdir, selection_params=stored)

        current = _selection_params_for_create(RecapRunCommand(date_from=date(2026, 4, 2)))
        result = _find_matching_resumable(tmp_path, 30, current)
        assert result is None


# ---------------------------------------------------------------------------
# Controller integration: --from / --to applied in run_pipeline
# ---------------------------------------------------------------------------


def _make_settings_mock(tmp_path: Path) -> MagicMock:
    return make_settings_mock(tmp_path)


def _make_articles_in_store(store_mock: MagicMock) -> list[DigestArticle]:
    """Return test articles spanning April 1-5 and configure the mock to return them."""
    articles = [
        DigestArticle(
            article_id=f"art-{i}",
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            source="s",
            published_at=f"2026-04-0{i + 1}T12:00:00+00:00",
            clean_text=f"body {i}",
        )
        for i in range(5)
    ]
    store_mock.return_value.list_retrieval_articles.return_value = articles
    return articles


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_from_sets_since_date_and_lookback(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    _make_articles_in_store(mock_store_cls)

    from_date = date(2026, 3, 20)
    cmd = RecapRunCommand(date_from=from_date)
    list(RecapCliController().run_pipeline(cmd))

    call_kwargs = mock_store_cls.return_value.list_retrieval_articles.call_args[1]
    assert call_kwargs["since"] == from_date
    expected_days = (_TODAY - from_date).days + 1
    assert call_kwargs["lookback_days"] == expected_days


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_to_filters_articles(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    articles = _make_articles_in_store(mock_store_cls)

    cmd = RecapRunCommand(date_from=date(2026, 4, 1), date_to=date(2026, 4, 2))
    list(RecapCliController().run_pipeline(cmd))

    pdir = Path(mock_flow.call_args[1]["pipeline_dir"])
    inp = read_pipeline_input(str(pdir))
    dates = {a.published_at[:10] for a in inp.articles}
    assert "2026-04-03" not in dates
    assert "2026-04-01" in dates or "2026-04-02" in dates


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_selection_params_persisted(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    _make_articles_in_store(mock_store_cls)

    cmd = RecapRunCommand(date_from=date(2026, 4, 1))
    list(RecapCliController().run_pipeline(cmd))

    pdir = Path(mock_flow.call_args[1]["pipeline_dir"])
    inp = read_pipeline_input(str(pdir))
    assert inp.selection_params is not None
    assert inp.selection_params["date_from"] == {"kind": "date", "value": "2026-04-01"}
    assert inp.selection_params["date_to"] is None


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_fresh_skips_resume(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    _make_articles_in_store(mock_store_cls)

    cmd = RecapRunCommand(date_from=date(2026, 4, 1))
    sel_params = _selection_params_for_create(cmd)
    workdir_root = settings.orchestrator.workdir_root
    pdir = workdir_root / f"pipeline-{_TODAY}-100000"
    _write_pipeline(pdir, selection_params=sel_params)

    fresh_cmd = RecapRunCommand(date_from=date(2026, 4, 1), fresh=True)
    messages = [text for _, text in RecapCliController().run_pipeline(fresh_cmd)]
    assert not any("Resuming" in m for m in messages)


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_runtime_override_still_resumes(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """--agent is a runtime-only override and should still resume a matching pipeline."""
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings

    cmd_orig = RecapRunCommand()
    sel_params = _selection_params_for_create(cmd_orig)
    workdir_root = settings.orchestrator.workdir_root
    pdir = workdir_root / f"pipeline-{_TODAY}-100000"
    _write_pipeline(pdir, selection_params=sel_params, completed_phases=["classify"])

    cmd_new = RecapRunCommand(agent_override="claude")
    messages = [text for _, text in RecapCliController().run_pipeline(cmd_new)]
    assert any("Resuming" in m for m in messages)


# ---------------------------------------------------------------------------
# _effective_to
# ---------------------------------------------------------------------------


class TestEffectiveTo:
    def test_both_none(self) -> None:
        assert _effective_to(None, None) is None

    def test_to_set(self) -> None:
        d = date(2026, 4, 3)
        assert _effective_to(None, d) is d

    def test_from_set_to_none_defaults_to_now(self) -> None:
        result = _effective_to(date(2026, 4, 1), None)
        assert type(result) is datetime
        assert result.tzinfo is not None

    def test_both_set_returns_to(self) -> None:
        d = date(2026, 4, 3)
        assert _effective_to(date(2026, 4, 1), d) is d


# ---------------------------------------------------------------------------
# --to only (no --from) through the controller
# ---------------------------------------------------------------------------


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_to_only_filters_articles(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """--to without --from still filters out articles after the cutoff."""
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    _make_articles_in_store(mock_store_cls)

    cmd = RecapRunCommand(date_to=date(2026, 4, 2))
    list(RecapCliController().run_pipeline(cmd))

    pdir = Path(mock_flow.call_args[1]["pipeline_dir"])
    inp = read_pipeline_input(str(pdir))
    dates = {a.published_at[:10] for a in inp.articles}
    assert "2026-04-03" not in dates
    assert "2026-04-04" not in dates
    assert "2026-04-05" not in dates


# ---------------------------------------------------------------------------
# --from with datetime (not just date)
# ---------------------------------------------------------------------------


@patch("news_recap.recap.launcher.recap_flow")
@patch("news_recap.recap.launcher.IngestionStore")
@patch("news_recap.recap.launcher.Settings.from_env")
def test_from_datetime_passes_datetime_as_since(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """--from with YYYY-MM-DDTHH:MM passes a datetime (not date) as since."""
    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    _make_articles_in_store(mock_store_cls)

    dt = datetime(2026, 3, 20, 14, 30, tzinfo=UTC)
    cmd = RecapRunCommand(date_from=dt)
    list(RecapCliController().run_pipeline(cmd))

    call_kwargs = mock_store_cls.return_value.list_retrieval_articles.call_args[1]
    assert call_kwargs["since"] is dt
    assert type(call_kwargs["since"]) is datetime


# ---------------------------------------------------------------------------
# PromptCliController with --from/--to
# ---------------------------------------------------------------------------


@patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True)
@patch("news_recap.recap.export_prompt.reorder_articles")
@patch("news_recap.recap.export_prompt.SentenceTransformerEmbedder")
@patch("news_recap.recap.export_prompt.IngestionStore")
@patch("news_recap.recap.export_prompt.Settings.from_env")
def test_prompt_no_ai_to_only_filters(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_embedder_cls: MagicMock,
    mock_reorder: MagicMock,
    mock_clipboard: MagicMock,
    tmp_path: Path,
) -> None:
    """prompt --no-ai --to filters articles after the cutoff."""
    from news_recap.recap.export_prompt import PromptCliController

    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings

    articles = [
        DigestArticle(
            article_id=f"art-{i}",
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            source="s",
            published_at=f"2026-04-0{i + 1}T12:00:00+00:00",
            clean_text=f"body {i}",
        )
        for i in range(5)
    ]
    mock_store_cls.return_value.list_retrieval_articles.return_value = articles
    mock_reorder.side_effect = lambda arts, *a, **kw: arts

    cmd = PromptCommand(ai=False, date_to=date(2026, 4, 2), out="clipboard")
    list(PromptCliController().prompt(cmd))

    kept = mock_reorder.call_args[0][0]
    kept_dates = {a.published_at[:10] for a in kept}
    assert "2026-04-01" in kept_dates
    assert "2026-04-02" in kept_dates
    assert "2026-04-03" not in kept_dates
    assert "2026-04-04" not in kept_dates
    assert "2026-04-05" not in kept_dates


@patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True)
@patch("news_recap.recap.export_prompt.SentenceTransformerEmbedder")
@patch("news_recap.recap.export_prompt.IngestionStore")
@patch("news_recap.recap.export_prompt.Settings.from_env")
def test_prompt_no_ai_from_sets_since(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_embedder_cls: MagicMock,
    mock_clipboard: MagicMock,
    tmp_path: Path,
) -> None:
    """prompt --no-ai --from passes the date as since to list_retrieval_articles."""
    from news_recap.recap.export_prompt import PromptCliController

    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings

    articles = [
        DigestArticle(
            article_id="art-0",
            title="Title",
            url="https://example.com/0",
            source="s",
            published_at="2026-04-01T12:00:00+00:00",
            clean_text="body",
        ),
    ]
    mock_store_cls.return_value.list_retrieval_articles.return_value = articles
    mock_embedder_cls.return_value.embed.return_value = [[0.1] * 10]

    from_date = date(2026, 3, 25)
    cmd = PromptCommand(ai=False, date_from=from_date, out="clipboard")
    list(PromptCliController().prompt(cmd))

    call_kwargs = mock_store_cls.return_value.list_retrieval_articles.call_args[1]
    assert call_kwargs["since"] == from_date
    expected_days = (_TODAY - from_date).days + 1
    assert call_kwargs["lookback_days"] == expected_days


@patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True)
@patch("news_recap.recap.export_prompt.SentenceTransformerEmbedder")
@patch("news_recap.recap.export_prompt.recap_flow")
@patch("news_recap.recap.export_prompt.IngestionStore")
@patch("news_recap.recap.export_prompt.Settings.from_env")
def test_prompt_ai_to_filters_articles_in_pipeline_input(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    mock_embedder_cls: MagicMock,
    mock_clipboard: MagicMock,
    tmp_path: Path,
) -> None:
    """prompt --ai --from --to: articles written to pipeline_input.json are filtered."""
    from news_recap.recap.export_prompt import PromptCliController
    from news_recap.recap.models import Digest

    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings

    articles = [
        DigestArticle(
            article_id=f"art-{i}",
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            source="s",
            published_at=f"2026-04-0{i + 1}T12:00:00+00:00",
            clean_text=f"body {i}",
        )
        for i in range(5)
    ]
    mock_store_cls.return_value.list_retrieval_articles.return_value = articles
    mock_embedder_cls.return_value.embed.side_effect = lambda texts: [[0.1] * 10 for _ in texts]

    kept_article = articles[0]

    def fake_flow(pipeline_dir: str, run_date: str, stop_after: str | None = None) -> None:
        from pathlib import Path

        digest = Digest(
            digest_id="d",
            run_date=run_date,
            status="completed",
            pipeline_dir=pipeline_dir,
            articles=[kept_article],
        )
        (Path(pipeline_dir) / "digest.json").write_bytes(msgspec.json.encode(digest))

    mock_flow.side_effect = fake_flow

    cmd = PromptCommand(
        ai=True,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 2),
        out="clipboard",
    )
    list(PromptCliController().prompt(cmd))

    pdir = Path(mock_flow.call_args[1]["pipeline_dir"])
    inp = read_pipeline_input(str(pdir))
    dates = {a.published_at[:10] for a in inp.articles}
    assert "2026-04-01" in dates
    assert "2026-04-02" in dates
    assert "2026-04-03" not in dates

    assert inp.selection_params is not None
    assert inp.selection_params["date_from"] == {"kind": "date", "value": "2026-04-01"}
    assert inp.selection_params["date_to"] == {"kind": "date", "value": "2026-04-02"}


def test_prompt_validation_from_with_max_days() -> None:
    """prompt --from + --max-days raises UsageError."""
    from news_recap.recap.export_prompt import PromptCliController

    cmd = PromptCommand(date_from=date(2026, 4, 1), max_days=5)
    with pytest.raises(Exception, match="--max-days"):
        list(PromptCliController().prompt(cmd))


# ---------------------------------------------------------------------------
# Regression: prompt --ai resumes with agent override
# ---------------------------------------------------------------------------


@patch("news_recap.recap.export_prompt._copy_to_clipboard", return_value=True)
@patch("news_recap.recap.export_prompt.SentenceTransformerEmbedder")
@patch("news_recap.recap.export_prompt.recap_flow")
@patch("news_recap.recap.export_prompt.IngestionStore")
@patch("news_recap.recap.export_prompt.Settings.from_env")
def test_prompt_ai_resume_applies_agent_override(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    mock_embedder_cls: MagicMock,
    mock_clipboard: MagicMock,
    tmp_path: Path,
) -> None:
    """prompt --ai --agent X on resume patches agent_override in pipeline_input.json."""
    from news_recap.recap.export_prompt import PromptCliController

    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings
    workdir_root = settings.orchestrator.workdir_root

    cmd_initial = PromptCommand(ai=True, date_from=date(2026, 4, 1))
    sel_params = _selection_params_for_prompt(cmd_initial)
    pdir = workdir_root / f"pipeline-{_TODAY}-100000"
    _write_pipeline(pdir, selection_params=sel_params, completed_phases=["classify"])

    kept = DigestArticle(
        article_id="art-0",
        title="T",
        url="https://e.com/0",
        source="s",
        published_at="2026-04-01T12:00:00+00:00",
        clean_text="b",
    )

    def fake_flow(pipeline_dir: str, run_date: str, stop_after: str | None = None) -> None:
        digest = Digest(
            digest_id="d",
            run_date=run_date,
            status="completed",
            pipeline_dir=pipeline_dir,
            articles=[kept],
        )
        (Path(pipeline_dir) / "digest.json").write_bytes(msgspec.json.encode(digest))

    mock_flow.side_effect = fake_flow
    mock_embedder_cls.return_value.embed.side_effect = lambda texts: [[0.1] * 10 for _ in texts]

    cmd_resume = PromptCommand(ai=True, date_from=date(2026, 4, 1), agent="gemini")
    list(PromptCliController().prompt(cmd_resume))

    inp = read_pipeline_input(str(pdir))
    assert inp.agent_override == "gemini"


# ---------------------------------------------------------------------------
# Regression: prompt --ai short-circuits on empty filtered articles
# ---------------------------------------------------------------------------


@patch("news_recap.recap.export_prompt.recap_flow")
@patch("news_recap.recap.export_prompt.IngestionStore")
@patch("news_recap.recap.export_prompt.Settings.from_env")
def test_prompt_ai_empty_after_filter_short_circuits(
    mock_env: MagicMock,
    mock_store_cls: MagicMock,
    mock_flow: MagicMock,
    tmp_path: Path,
) -> None:
    """prompt --ai with date filters leaving zero articles emits 'No articles found.'."""
    from news_recap.recap.export_prompt import PromptCliController

    settings = _make_settings_mock(tmp_path)
    mock_env.return_value = settings

    articles = [
        DigestArticle(
            article_id="art-0",
            title="Title",
            url="https://example.com/0",
            source="s",
            published_at="2026-04-05T12:00:00+00:00",
            clean_text="body",
        ),
    ]
    mock_store_cls.return_value.list_retrieval_articles.return_value = articles

    cmd = PromptCommand(
        ai=True,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 2),
    )
    messages = list(PromptCliController().prompt(cmd))

    mock_flow.assert_not_called()
    assert any("No articles found" in text for _, text in messages)
