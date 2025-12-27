from __future__ import annotations

import json
from typing import Any


def extract_file_path(tool_input: dict[str, Any]) -> str | None:
    return tool_input.get("path") or tool_input.get("file_path")


def extract_command(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    if tool_name == "bash":
        return tool_input.get("command")
    return None


def _stringify_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=True)


def parse_message(
    raw: dict[str, Any],
    session_id: str,
    seq: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    message_id = raw.get("uuid") or f"{session_id}-{seq}"
    message_block = raw.get("message") or {}

    role = None
    if isinstance(message_block, dict):
        role = message_block.get("role")
    if not role:
        role = raw.get("type")

    message: dict[str, Any] = {
        "message_id": message_id,
        "session_id": session_id,
        "sequence_num": seq,
        "role": role or "unknown",
        "timestamp": raw.get("timestamp"),
        "cost_usd": raw.get("costUSD"),
        "duration_ms": raw.get("durationMs"),
        "thinking_content": raw.get("thinking"),
    }

    text_parts: list[str] = []
    tool_usages: list[dict[str, Any]] = []
    tool_lookup: dict[str, dict[str, Any]] = {}

    content = message_block.get("content") if isinstance(message_block, dict) else message_block

    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                tool_usage = {
                    "tool_usage_id": block.get("id"),
                    "message_id": message_id,
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "tool_input": json.dumps(tool_input, ensure_ascii=True),
                    "tool_result": None,
                    "is_error": False,
                    "file_path": extract_file_path(tool_input),
                    "command": extract_command(tool_name, tool_input),
                }
                tool_usages.append(tool_usage)
                tool_usage_id = tool_usage.get("tool_usage_id")
                if isinstance(tool_usage_id, str) and tool_usage_id:
                    tool_lookup[tool_usage_id] = tool_usage
            elif block_type == "tool_result":
                tool_id = block.get("tool_use_id")
                tool_usage = tool_lookup.get(tool_id)
                if tool_usage is not None:
                    tool_usage["tool_result"] = _stringify_tool_content(block.get("content"))
                    tool_usage["is_error"] = bool(block.get("is_error", False))
    elif content is not None:
        text_parts.append(str(content))

    message["text_content"] = "\n".join([part for part in text_parts if part])
    message["searchable_text"] = "\n".join(
        [part for part in [message.get("text_content"), message.get("thinking_content")] if part]
    )

    return message, tool_usages
