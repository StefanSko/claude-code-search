from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOCAL_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
ENV_SESSIONS_DIR = "CLAUDE_CODE_SESSIONS_DIR"
ENV_PROJECTS_DIR = "CLAUDE_CODE_PROJECTS_DIR"


def resolve_local_sessions_dir(root_dir: Path | None = None) -> Path:
    if root_dir is not None:
        return root_dir
    env_value = os.environ.get(ENV_SESSIONS_DIR)
    if env_value:
        return Path(env_value).expanduser()
    return LOCAL_SESSIONS_DIR


def resolve_projects_dir(root_dir: Path | None = None) -> Path:
    if root_dir is not None:
        return root_dir
    env_value = os.environ.get(ENV_PROJECTS_DIR)
    if env_value:
        return Path(env_value).expanduser()
    return PROJECTS_DIR


def discover_local_sessions(root_dir: Path | None = None) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []

    sessions_dir = resolve_local_sessions_dir(root_dir)
    if sessions_dir.exists():
        sessions.extend(_discover_sessions_dir(sessions_dir))

    projects_dir = resolve_projects_dir()
    if projects_dir.exists():
        sessions.extend(_discover_projects_dir(projects_dir))

    sessions.sort(key=lambda item: item["modified"], reverse=True)
    return sessions


def load_local_session(
    session_id: str,
    root_dir: Path | None = None,
    session_path: str | None = None,
) -> list[dict[str, Any]]:
    if session_path:
        path = Path(session_path)
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_path}")
        return _read_jsonl(path)

    session_path_candidate = Path(session_id)
    if session_path_candidate.suffix == ".jsonl" and session_path_candidate.exists():
        return _read_jsonl(session_path_candidate)

    sessions_dir = resolve_local_sessions_dir(root_dir)
    messages_file = sessions_dir / session_id / "messages.jsonl"
    if not messages_file.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    return _read_jsonl(messages_file)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        messages.append(json.loads(line))
    return messages


def _extract_preview(messages_file: Path) -> tuple[str, int]:
    preview = ""
    message_count = 0
    for line in messages_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        message_count += 1
        if not preview:
            raw = json.loads(line)
            preview = _extract_preview_text(raw)
    if preview:
        preview = preview.replace("\n", " ").strip()
    return preview, message_count


def _extract_preview_text(raw: dict[str, Any]) -> str:
    message = raw.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else message
    if isinstance(content, str):
        return content[:120]
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return (block.get("text") or "")[:120]
    return ""


def _load_session_metadata(session_dir: Path) -> dict[str, Any]:
    for name in ("session.json", "metadata.json"):
        metadata_path = session_dir / name
        if metadata_path.exists():
            data = json.loads(metadata_path.read_text())
            return _normalize_metadata(data)
    return {}


def _normalize_metadata(data: dict[str, Any]) -> dict[str, Any]:
    project_directory = (
        data.get("project_directory")
        or data.get("projectDir")
        or data.get("projectPath")
        or data.get("cwd")
    )
    created_at = data.get("created_at") or data.get("createdAt") or data.get("start_time")
    if isinstance(created_at, (int, float)):
        created_at = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()
    return {
        "project_directory": project_directory,
        "created_at": created_at,
    }


def _discover_sessions_dir(sessions_dir: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        messages_file = session_dir / "messages.jsonl"
        if not messages_file.exists():
            continue

        metadata = _load_session_metadata(session_dir)
        preview, message_count = _extract_preview(messages_file)
        modified = messages_file.stat().st_mtime

        sessions.append(
            {
                "id": session_dir.name,
                "path": str(messages_file),
                "source": "local",
                "modified": modified,
                "preview": preview,
                "message_count": message_count,
                "project_directory": metadata.get("project_directory"),
                "created_at": metadata.get("created_at"),
            }
        )
    return sessions


def _discover_projects_dir(projects_dir: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for session_file in project_dir.glob("*.jsonl"):
            if not _is_session_jsonl(session_file):
                continue
            preview, message_count = _extract_preview(session_file)
            modified = session_file.stat().st_mtime
            session_id = f"proj:{project_dir.name}/{session_file.stem}"

            sessions.append(
                {
                    "id": session_id,
                    "path": str(session_file),
                    "source": "local",
                    "modified": modified,
                    "preview": preview,
                    "message_count": message_count,
                    "project_directory": str(project_dir),
                    "created_at": None,
                }
            )
    return sessions


def _is_session_jsonl(path: Path) -> bool:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return False
        if isinstance(payload, dict) and ("message" in payload or "uuid" in payload):
            return True
        return False
    return False
