# ABOUTME: Base classes and types for session loaders.
# ABOUTME: Defines SessionInfo dataclass and abstract SessionLoader interface.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SessionInfo:
    """Information about a Claude Code session."""

    session_id: str
    source: str  # 'local' or 'web'
    path: Path | None  # File path for local sessions
    modified_at: datetime
    preview: str  # First message preview
    message_count: int
    project_directory: str | None = None


class SessionLoader(ABC):
    """Abstract base class for session loaders."""

    @abstractmethod
    def discover_sessions(self) -> list[SessionInfo]:
        """Discover available sessions."""
        ...

    @abstractmethod
    def load_session(self, session_id: str) -> list[dict]:
        """Load all messages from a session."""
        ...
