# ABOUTME: Message parsing utilities for Claude Code sessions.
# ABOUTME: Extracts structured data from raw JSONL message format.

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ToolUsage:
    """A single tool invocation within a message."""

    tool_usage_id: str
    message_id: str
    session_id: str
    tool_name: str
    tool_input: str  # JSON string
    tool_result: str | None = None
    is_error: bool = False
    file_path: str | None = None
    command: str | None = None


@dataclass
class ParsedMessage:
    """A parsed message with extracted content."""

    message_id: str
    session_id: str
    sequence_num: int
    role: str
    timestamp: str | None
    text_content: str
    thinking_content: str | None
    searchable_text: str
    cost_usd: float | None = None
    duration_ms: int | None = None
    tool_usages: list[ToolUsage] = field(default_factory=list)


def parse_message(raw: dict, session_id: str, seq: int) -> ParsedMessage:
    """Parse a raw message into structured data."""
    message_id = raw.get("uuid", f"{session_id}-{seq}")
    role = raw.get("message", {}).get("role", raw.get("type", "unknown"))
    timestamp = raw.get("timestamp")
    cost_usd = raw.get("costUSD")
    duration_ms = raw.get("durationMs")
    thinking_content = raw.get("thinking")

    text_parts: list[str] = []
    tool_usages: list[ToolUsage] = []
    pending_tools: dict[str, ToolUsage] = {}

    content = raw.get("message", {}).get("content", [])
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            block_type = block.get("type")

            if block_type == "text":
                text_parts.append(block.get("text", ""))

            elif block_type == "tool_use":
                tool_id = block.get("id", "")
                tool = ToolUsage(
                    tool_usage_id=tool_id,
                    message_id=message_id,
                    session_id=session_id,
                    tool_name=block.get("name", ""),
                    tool_input=json.dumps(block.get("input", {})),
                    file_path=_extract_file_path(block),
                    command=_extract_command(block),
                )
                pending_tools[tool_id] = tool
                tool_usages.append(tool)

            elif block_type == "tool_result":
                tool_id = block.get("tool_use_id", "")
                if tool_id in pending_tools:
                    tool = pending_tools[tool_id]
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        result_parts = []
                        for part in result_content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                result_parts.append(part.get("text", ""))
                            elif isinstance(part, str):
                                result_parts.append(part)
                        result_content = "\n".join(result_parts)
                    tool.tool_result = str(result_content)
                    tool.is_error = block.get("is_error", False)

    text_content = "\n".join(text_parts)
    searchable_text = "\n".join(filter(None, [text_content, thinking_content]))

    return ParsedMessage(
        message_id=message_id,
        session_id=session_id,
        sequence_num=seq,
        role=role,
        timestamp=timestamp,
        text_content=text_content,
        thinking_content=thinking_content,
        searchable_text=searchable_text,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        tool_usages=tool_usages,
    )


def _extract_file_path(block: dict) -> str | None:
    """Extract file path from tool input."""
    tool_input = block.get("input", {})
    return tool_input.get("path") or tool_input.get("file_path")


def _extract_command(block: dict) -> str | None:
    """Extract command from bash tool input."""
    if block.get("name") == "Bash":
        return block.get("input", {}).get("command")
    return None
