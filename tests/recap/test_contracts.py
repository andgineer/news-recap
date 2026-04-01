from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.contracts import TaskManifest, read_manifest, write_json


def test_read_manifest_valid(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "articles_index_path": "/w/articles.json",
        "contract_version": 2,
        "output_result_path": "/w/result.json",
        "output_stderr_path": "/w/stderr.txt",
        "output_stdout_path": "/w/stdout.txt",
        "task_id": "tid-1",
        "task_input_path": "/w/input.json",
        "task_type": "recap_enrich",
        "workdir": "/w",
    }
    write_json(path, payload)
    manifest = read_manifest(path)
    assert manifest == TaskManifest(
        contract_version=2,
        task_id="tid-1",
        task_type="recap_enrich",
        workdir="/w",
        task_input_path="/w/input.json",
        articles_index_path="/w/articles.json",
        output_result_path="/w/result.json",
        output_stdout_path="/w/stdout.txt",
        output_stderr_path="/w/stderr.txt",
    )


def test_read_manifest_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "articles_index_path": "/w/articles.json",
        "output_result_path": "/w/result.json",
        "output_stderr_path": "/w/stderr.txt",
        "output_stdout_path": "/w/stdout.txt",
        "task_type": "recap_enrich",
        "task_input_path": "/w/input.json",
        "workdir": "/w",
    }
    write_json(path, payload)
    with pytest.raises(ValueError, match="missing") as exc_info:
        read_manifest(path)
    assert "task_id" in str(exc_info.value)


def test_read_manifest_invalid_version(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "articles_index_path": "/w/articles.json",
        "contract_version": 0,
        "output_result_path": "/w/result.json",
        "output_stderr_path": "/w/stderr.txt",
        "output_stdout_path": "/w/stdout.txt",
        "task_id": "tid-1",
        "task_input_path": "/w/input.json",
        "task_type": "recap_enrich",
        "workdir": "/w",
    }
    write_json(path, payload)
    with pytest.raises(ValueError, match="contract_version"):
        read_manifest(path)


def test_read_manifest_defaults_version_to_1(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "articles_index_path": "/w/articles.json",
        "output_result_path": "/w/result.json",
        "output_stderr_path": "/w/stderr.txt",
        "output_stdout_path": "/w/stdout.txt",
        "task_id": "tid-1",
        "task_input_path": "/w/input.json",
        "task_type": "recap_enrich",
        "workdir": "/w",
    }
    write_json(path, payload)
    manifest = read_manifest(path)
    assert manifest.contract_version == 1
