"""Tests for workdir materialization with contract v3 features."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_recap.brain.contracts import (
    ArticleIndexEntry,
    TaskInputContract,
    read_manifest,
)
from news_recap.brain.workdir import TaskWorkdirManager


@pytest.fixture
def workdir_manager(tmp_path: Path) -> TaskWorkdirManager:
    return TaskWorkdirManager(tmp_path)


class TestV2BackwardCompatibility:
    def test_v2_without_extras(self, workdir_manager):
        result = workdir_manager.materialize(
            task_id="t1",
            task_type="highlights",
            task_input=TaskInputContract(task_type="highlights", prompt="test"),
            articles_index=[
                ArticleIndexEntry(source_id="a1", title="T", url="http://ex.com"),
            ],
        )
        assert result.manifest.contract_version == 2
        assert result.manifest.input_resources_dir is None
        assert result.manifest.output_results_dir is None
        assert result.manifest.output_schema_hint is None


class TestV3WithExtraFiles:
    def test_extra_input_files_create_resources_dir(self, workdir_manager):
        result = workdir_manager.materialize(
            task_id="t2",
            task_type="recap_enrich",
            task_input=TaskInputContract(task_type="recap_enrich", prompt="test"),
            articles_index=[],
            extra_input_files={
                "article_a1.json": '{"article_id": "a1", "text": "hello"}',
            },
        )
        assert result.manifest.contract_version == 3
        assert result.manifest.input_resources_dir is not None
        resources_dir = Path(result.manifest.input_resources_dir)
        assert resources_dir.exists()
        assert (resources_dir / "article_a1.json").exists()
        content = json.loads((resources_dir / "article_a1.json").read_text())
        assert content["article_id"] == "a1"

    def test_output_results_dir_created(self, workdir_manager):
        result = workdir_manager.materialize(
            task_id="t3",
            task_type="recap_synthesize",
            task_input=TaskInputContract(task_type="recap_synthesize", prompt="test"),
            articles_index=[],
            extra_input_files={"event.json": "{}"},
        )
        assert result.manifest.output_results_dir is not None
        assert Path(result.manifest.output_results_dir).exists()

    def test_schema_hint_stored_in_manifest(self, workdir_manager):
        result = workdir_manager.materialize(
            task_id="t4",
            task_type="recap_classify",
            task_input=TaskInputContract(task_type="recap_classify", prompt="test"),
            articles_index=[],
            output_schema_hint='{"articles": []}',
        )
        assert result.manifest.contract_version == 3
        assert result.manifest.output_schema_hint == '{"articles": []}'

    def test_manifest_round_trip(self, workdir_manager):
        result = workdir_manager.materialize(
            task_id="t5",
            task_type="recap_group",
            task_input=TaskInputContract(task_type="recap_group", prompt="test"),
            articles_index=[],
            extra_input_files={"data.json": "{}"},
            output_schema_hint="custom schema",
        )
        loaded = read_manifest(result.manifest_path)
        assert loaded.contract_version == 3
        assert loaded.input_resources_dir == result.manifest.input_resources_dir
        assert loaded.output_results_dir == result.manifest.output_results_dir
        assert loaded.output_schema_hint == "custom schema"

    def test_bytes_extra_input_files(self, workdir_manager):
        result = workdir_manager.materialize(
            task_id="t6",
            task_type="recap_enrich",
            task_input=TaskInputContract(task_type="recap_enrich", prompt="test"),
            articles_index=[],
            extra_input_files={
                "binary_data.bin": b"binary content here",
            },
        )
        resources_dir = Path(result.manifest.input_resources_dir)
        assert (resources_dir / "binary_data.bin").read_bytes() == b"binary content here"
