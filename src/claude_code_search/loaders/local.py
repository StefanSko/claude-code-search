# ABOUTME: Local session loader for reading Claude Code sessions from disk.
# ABOUTME: Discovers sessions in ~/.claude/projects/ directory structure.

import json
from datetime import UTC, datetime
from pathlib import Path

from claude_code_search.loaders.base import SessionInfo, SessionLoader


class LocalSessionLoader(SessionLoader):
    """Loader for local Claude Code sessions stored on disk."""

    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path.home() / ".claude" / "projects"

    def discover_sessions(self) -> list[SessionInfo]:
        """Find all local Claude Code sessions."""
        sessions: list[SessionInfo] = []

        if not self.base_path.exists():
            return sessions

        for project_dir in self.base_path.iterdir():
            if not project_dir.is_dir():
                continue

            for session_file in project_dir.glob("*.jsonl"):
                session_info = self._parse_session_file(session_file, project_dir.name)
                if session_info:
                    sessions.append(session_info)

        return sorted(sessions, key=lambda s: s.modified_at, reverse=True)

    def _parse_session_file(
        self, session_file: Path, project_name: str
    ) -> SessionInfo | None:
        """Parse a session file to extract metadata."""
        try:
            messages = self._read_messages(session_file)
            if not messages:
                return None

            first_user_msg = next(
                (m for m in messages if m.get("type") == "user"),
                None,
            )
            preview = ""
            if first_user_msg:
                content = first_user_msg.get("message", {}).get("content", "")
                if isinstance(content, str):
                    preview = content[:100]
                elif isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text":
                            preview = block.get("text", "")[:100]
                            break

            last_msg = messages[-1] if messages else {}
            timestamp_str = last_msg.get("timestamp")
            if timestamp_str:
                modified_at = datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                )
            else:
                modified_at = datetime.fromtimestamp(
                    session_file.stat().st_mtime, tz=UTC
                )

            return SessionInfo(
                session_id=session_file.stem,
                source="local",
                path=session_file,
                modified_at=modified_at,
                preview=preview,
                message_count=len(messages),
                project_directory=project_name,
            )
        except (json.JSONDecodeError, OSError):
            return None

    def _read_messages(self, session_file: Path) -> list[dict]:
        """Read all messages from a JSONL session file."""
        messages: list[dict] = []
        with session_file.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return messages

    def load_session(self, session_id: str) -> list[dict]:
        """Load all messages from a session by ID."""
        for project_dir in self.base_path.iterdir():
            if not project_dir.is_dir():
                continue

            session_file = project_dir / f"{session_id}.jsonl"
            if session_file.exists():
                return self._read_messages(session_file)

        return []
