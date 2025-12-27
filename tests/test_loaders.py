# ABOUTME: Tests for session loader functionality.
# ABOUTME: Verifies discovery and loading of local Claude Code sessions.

import json
from pathlib import Path

from claude_code_search.loaders.local import LocalSessionLoader


class TestLocalSessionLoader:
    """Tests for the LocalSessionLoader class."""

    def test_discover_sessions_empty_dir(self, tmp_path: Path) -> None:
        """Discover returns empty list for empty directory."""
        loader = LocalSessionLoader(tmp_path)
        sessions = loader.discover_sessions()

        assert sessions == []

    def test_discover_sessions_nonexistent_dir(self, tmp_path: Path) -> None:
        """Discover returns empty list for non-existent directory."""
        loader = LocalSessionLoader(tmp_path / "nonexistent")
        sessions = loader.discover_sessions()

        assert sessions == []

    def test_discover_sessions_finds_jsonl(self, tmp_path: Path) -> None:
        """Discover finds JSONL session files."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        session_file = project_dir / "session-123.jsonl"
        messages = [
            {
                "uuid": "msg-1",
                "type": "user",
                "message": {"role": "user", "content": "Hello"},
                "timestamp": "2024-12-25T10:00:00Z",
            }
        ]
        with session_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        loader = LocalSessionLoader(tmp_path)
        sessions = loader.discover_sessions()

        assert len(sessions) == 1
        assert sessions[0].session_id == "session-123"
        assert sessions[0].source == "local"
        assert sessions[0].project_directory == "my-project"
        assert sessions[0].message_count == 1

    def test_load_session(self, tmp_path: Path) -> None:
        """Load messages from a session file."""
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        session_file = project_dir / "session-456.jsonl"
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "First"}},
            {"uuid": "msg-2", "message": {"role": "assistant", "content": "Second"}},
        ]
        with session_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        loader = LocalSessionLoader(tmp_path)
        loaded = loader.load_session("session-456")

        assert len(loaded) == 2
        assert loaded[0]["uuid"] == "msg-1"
        assert loaded[1]["uuid"] == "msg-2"

    def test_load_session_not_found(self, tmp_path: Path) -> None:
        """Load returns empty list for non-existent session."""
        loader = LocalSessionLoader(tmp_path)
        loaded = loader.load_session("nonexistent")

        assert loaded == []

    def test_discover_extracts_preview(self, tmp_path: Path) -> None:
        """Discover extracts preview from first user message."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        session_file = project_dir / "session.jsonl"
        messages = [
            {
                "uuid": "msg-1",
                "type": "user",
                "message": {"role": "user", "content": "Create a Python web server"},
            }
        ]
        with session_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        loader = LocalSessionLoader(tmp_path)
        sessions = loader.discover_sessions()

        assert sessions[0].preview == "Create a Python web server"

    def test_discover_handles_malformed_json(self, tmp_path: Path) -> None:
        """Discover skips malformed JSON lines."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        session_file = project_dir / "session.jsonl"
        with session_file.open("w") as f:
            f.write('{"valid": "json"}\n')
            f.write("not valid json\n")
            f.write('{"also": "valid"}\n')

        loader = LocalSessionLoader(tmp_path)
        messages = loader.load_session("session")

        assert len(messages) == 2
