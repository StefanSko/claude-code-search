from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from claude_code_search.cli import cli
from claude_code_search.index import SearchIndex


def _build_index(db_path: Path, sample_session_messages: list[dict]) -> None:
    index = SearchIndex(str(db_path))
    index.index_session(
        session_id="session-123",
        messages=sample_session_messages,
        source="local",
        session_path="/tmp/session-123/messages.jsonl",
    )


def test_cli_search_json(tmp_path: Path, sample_session_messages: list[dict]) -> None:
    db_path = tmp_path / "index.duckdb"
    _build_index(db_path, sample_session_messages)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["search", "Click", "--db", str(db_path), "--format", "json", "--limit", "1"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload
    assert payload[0]["session_id"] == "session-123"


def test_cli_list_sessions(tmp_path: Path, sample_session_messages: list[dict]) -> None:
    db_path = tmp_path / "index.duckdb"
    _build_index(db_path, sample_session_messages)

    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "session-123" in result.output
