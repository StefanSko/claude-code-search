from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

API_BASE_URL = os.environ.get("CLAUDE_CODE_API_BASE", "https://api.anthropic.com")


def discover_web_sessions() -> list[dict[str, Any]]:
    sessions = fetch_web_sessions()
    discovered: list[dict[str, Any]] = []
    for session in sessions:
        discovered.append(
            {
                "id": session.get("id") or session.get("session_id"),
                "source": "web",
                "created_at": session.get("created_at"),
                "modified": session.get("updated_at"),
                "preview": session.get("title") or "",
                "message_count": session.get("message_count"),
                "project_directory": session.get("project_directory"),
            }
        )
    return discovered


def load_web_session(session_id: str) -> list[dict[str, Any]]:
    token = get_oauth_token()
    org_uuid = get_org_uuid()
    url = f"{API_BASE_URL}/v1/sessions/{session_id}/messages"
    response = httpx.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "x-organization-uuid": org_uuid,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    if "messages" in data:
        return data["messages"]
    return data


def fetch_web_sessions() -> list[dict[str, Any]]:
    token = get_oauth_token()
    org_uuid = get_org_uuid()
    response = httpx.get(
        f"{API_BASE_URL}/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "x-organization-uuid": org_uuid,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("sessions", [])


def get_oauth_token() -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            os.environ.get("USER", ""),
            "-w",
            "-s",
            "Claude Code-credentials",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    creds = json.loads(result.stdout)
    return creds["claudeAiOauth"]["accessToken"]


def get_org_uuid() -> str:
    config_path = Path.home() / ".claude.json"
    data = json.loads(config_path.read_text())
    return data["oauthAccount"]["organizationUuid"]
