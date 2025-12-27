from __future__ import annotations

from pathlib import Path
from typing import Any

from .local import discover_local_sessions, load_local_session
from .web import discover_web_sessions, load_web_session

__all__ = ["discover_sessions", "load_session", "resolve_session_metadata"]


def discover_sessions(source: str = "all", root_dir: Path | None = None) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    if source in {"all", "local"}:
        sessions.extend(discover_local_sessions(root_dir=root_dir))
    if source in {"all", "web"}:
        sessions.extend(discover_web_sessions())

    sessions.sort(key=_sort_key, reverse=True)
    return sessions


def resolve_session_metadata(
    session_id: str,
    source: str = "all",
    root_dir: Path | None = None,
) -> dict[str, Any] | None:
    sessions = discover_sessions(source=source, root_dir=root_dir)
    for session in sessions:
        if session.get("id") == session_id:
            return session
    return None


def load_session(
    session_id: str,
    source: str = "all",
    root_dir: Path | None = None,
    session_path: str | None = None,
) -> list[dict[str, Any]]:
    if source == "local":
        return load_local_session(session_id, root_dir=root_dir, session_path=session_path)
    if source == "web":
        return load_web_session(session_id)

    try:
        return load_local_session(session_id, root_dir=root_dir, session_path=session_path)
    except FileNotFoundError:
        return load_web_session(session_id)


def _sort_key(session: dict[str, Any]) -> float:
    modified = session.get("modified")
    if isinstance(modified, (int, float)):
        return float(modified)
    return 0.0
