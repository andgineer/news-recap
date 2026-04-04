from __future__ import annotations

from pathlib import Path

import pytest

from news_recap.recap.contracts import TaskManifest, read_manifest, write_json


def test_read_manifest_valid(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "contract_version": 2,
        "task_id": "tid-1",
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
    )


def test_read_manifest_derived_paths() -> None:
    m = TaskManifest(contract_version=2, task_id="t", task_type="x", workdir="/w")
    assert m.task_input_path == Path("/w/input/task_input.json")
    assert m.output_stdout_path == Path("/w/output/agent_stdout.log")
    assert m.output_stderr_path == Path("/w/output/agent_stderr.log")


def test_read_manifest_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "task_type": "recap_enrich",
        "workdir": "/w",
    }
    write_json(path, payload)
    with pytest.raises(ValueError, match="missing") as exc_info:
        read_manifest(path)
    assert "task_id" in str(exc_info.value)


def test_read_manifest_invalid_version(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "contract_version": 0,
        "task_id": "tid-1",
        "task_type": "recap_enrich",
        "workdir": "/w",
    }
    write_json(path, payload)
    with pytest.raises(ValueError, match="contract_version"):
        read_manifest(path)


def test_read_manifest_defaults_version_to_1(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "task_id": "tid-1",
        "task_type": "recap_enrich",
        "workdir": "/w",
    }
    write_json(path, payload)
    manifest = read_manifest(path)
    assert manifest.contract_version == 1
