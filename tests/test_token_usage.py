"""Tests for agent token usage parsing, saving, and reading."""

from __future__ import annotations

import json
from pathlib import Path

from news_recap.recap.agents.ai_agent import (
    _parse_tokens_used,
    _save_usage,
    read_agent_usage,
)


class TestParseTokensUsed:
    def test_codex_format(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr.log"
        stderr.write_text("OpenAI Codex v0.104.0\n...\ntokens used\n12,033\n")
        assert _parse_tokens_used(stderr) == 12033

    def test_codex_no_commas(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr.log"
        stderr.write_text("stuff\ntokens used\n500\n")
        assert _parse_tokens_used(stderr) == 500

    def test_large_number(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr.log"
        stderr.write_text("tokens used\n1,234,567\n")
        assert _parse_tokens_used(stderr) == 1234567

    def test_no_token_info(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr.log"
        stderr.write_text("Loaded cached credentials.\n")
        assert _parse_tokens_used(stderr) is None

    def test_empty_file(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr.log"
        stderr.write_text("")
        assert _parse_tokens_used(stderr) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert _parse_tokens_used(tmp_path / "nonexistent") is None

    def test_claude_empty_stderr(self, tmp_path: Path) -> None:
        stderr = tmp_path / "stderr.log"
        stderr.write_text("\n")
        assert _parse_tokens_used(stderr) is None


class TestSaveAndReadUsage:
    def test_round_trip_with_tokens(self, tmp_path: Path) -> None:
        _save_usage(tmp_path, elapsed=42.5, tokens=12033)
        elapsed, tokens = read_agent_usage(tmp_path)
        assert elapsed == 42.5
        assert tokens == 12033

    def test_round_trip_without_tokens(self, tmp_path: Path) -> None:
        _save_usage(tmp_path, elapsed=10.0, tokens=None)
        elapsed, tokens = read_agent_usage(tmp_path)
        assert elapsed == 10.0
        assert tokens == 0

    def test_missing_file_returns_zeros(self, tmp_path: Path) -> None:
        elapsed, tokens = read_agent_usage(tmp_path)
        assert elapsed == 0.0
        assert tokens == 0

    def test_corrupted_json_returns_zeros(self, tmp_path: Path) -> None:
        path = tmp_path / "meta" / "usage.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json")
        elapsed, tokens = read_agent_usage(tmp_path)
        assert elapsed == 0.0
        assert tokens == 0

    def test_file_structure(self, tmp_path: Path) -> None:
        _save_usage(tmp_path, elapsed=5.3, tokens=999)
        data = json.loads((tmp_path / "meta" / "usage.json").read_text())
        assert data["elapsed_seconds"] == 5.3
        assert data["tokens_used"] == 999
        assert data["total_tokens"] == 999
        assert data["backend"] == "cli"
