"""Tests for recap task type validation in the output contract validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_recap.orchestrator.contracts import TaskManifest
from news_recap.orchestrator.validator import ValidationResult, validate_output_contract


@pytest.fixture
def tmp_output(tmp_path: Path):
    """Helper to write JSON output and return path."""

    def _write(data: dict) -> Path:
        path = tmp_path / "agent_result.json"
        path.write_text(json.dumps(data), "utf-8")
        return path

    return _write


@pytest.fixture
def manifest(tmp_path: Path) -> TaskManifest:
    return TaskManifest(
        contract_version=3,
        task_id="test-123",
        task_type="recap_classify",
        workdir=str(tmp_path),
        task_input_path=str(tmp_path / "input" / "task_input.json"),
        articles_index_path=str(tmp_path / "input" / "articles_index.json"),
        output_result_path=str(tmp_path / "output" / "agent_result.json"),
        output_stdout_path=str(tmp_path / "output" / "agent_stdout.log"),
        output_stderr_path=str(tmp_path / "output" / "agent_stderr.log"),
        output_schema_hint="custom schema",
    )


class TestRecapClassifyValidation:
    def test_valid_classify_output(self, tmp_output, manifest):
        path = tmp_output({
            "articles": [
                {"article_id": "a1", "decision": "keep", "reason": "relevant", "needs_resource": True}
            ]
        })
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_classify",
            manifest=manifest,
        )
        assert result.is_valid
        assert result.payload is not None

    def test_classify_empty_articles(self, tmp_output, manifest):
        path = tmp_output({"articles": []})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_classify",
            manifest=manifest,
        )
        assert not result.is_valid
        assert "non-empty" in (result.error_summary or "")

    def test_classify_missing_fields(self, tmp_output, manifest):
        path = tmp_output({"articles": [{"article_id": "a1"}]})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_classify",
            manifest=manifest,
        )
        assert not result.is_valid
        assert "decision" in (result.error_summary or "")


class TestRecapGroupValidation:
    def test_valid_group_output(self, tmp_output, manifest):
        path = tmp_output({
            "events": [
                {"event_id": "evt_1", "title": "Test", "article_ids": ["a1"], "significance": "high"}
            ]
        })
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_group",
            manifest=manifest,
        )
        assert result.is_valid

    def test_group_missing_events(self, tmp_output, manifest):
        path = tmp_output({"something_else": []})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_group",
            manifest=manifest,
        )
        assert not result.is_valid

    def test_group_event_missing_fields(self, tmp_output, manifest):
        path = tmp_output({"events": [{"title": "test"}]})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_group",
            manifest=manifest,
        )
        assert not result.is_valid
        assert "event_id" in (result.error_summary or "")


class TestRecapComposeValidation:
    def test_valid_compose_output(self, tmp_output, manifest):
        path = tmp_output({
            "theme_blocks": [
                {
                    "theme": "International",
                    "recaps": [{"headline": "Test", "body": "...", "sources": []}],
                }
            ]
        })
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_compose",
            manifest=manifest,
        )
        assert result.is_valid

    def test_compose_empty_theme_blocks(self, tmp_output, manifest):
        path = tmp_output({"theme_blocks": []})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_compose",
            manifest=manifest,
        )
        assert not result.is_valid


class TestRecapEnrichValidation:
    def test_valid_enrich_output(self, tmp_output, manifest):
        path = tmp_output({"enriched": [{"article_id": "a1", "new_title": "T", "clean_text": "..."}]})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_enrich",
            manifest=manifest,
        )
        assert result.is_valid

    def test_enrich_missing_key(self, tmp_output, manifest):
        path = tmp_output({"results": []})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_enrich",
            manifest=manifest,
        )
        assert not result.is_valid


class TestRecapSynthesizeValidation:
    def test_valid_synthesize_output(self, tmp_output, manifest):
        path = tmp_output({"status": "completed", "processed": 5})
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_synthesize",
            manifest=manifest,
        )
        assert result.is_valid


class TestBlocksBackwardCompatibility:
    """Ensure non-recap task types still use blocks[] validation."""

    def test_blocks_validation_still_works(self, tmp_output):
        path = tmp_output({
            "blocks": [{"text": "hello", "source_ids": ["a1"]}],
            "metadata": {},
        })
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids={"a1"},
            task_type="highlights",
        )
        assert result.is_valid

    def test_blocks_unknown_source_rejected(self, tmp_output):
        path = tmp_output({
            "blocks": [{"text": "hello", "source_ids": ["unknown"]}],
            "metadata": {},
        })
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids={"a1"},
            task_type="highlights",
        )
        assert not result.is_valid

    def test_default_task_type_uses_blocks(self, tmp_output):
        path = tmp_output({
            "blocks": [{"text": "hello", "source_ids": ["a1"]}],
            "metadata": {},
        })
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids={"a1"},
        )
        assert result.is_valid


class TestMissingAndInvalidOutput:
    def test_missing_file(self, tmp_path):
        result = validate_output_contract(
            output_path=tmp_path / "nonexistent.json",
            allowed_source_ids=set(),
            task_type="recap_classify",
        )
        assert not result.is_valid

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json at all")
        result = validate_output_contract(
            output_path=path,
            allowed_source_ids=set(),
            task_type="recap_classify",
        )
        assert not result.is_valid
