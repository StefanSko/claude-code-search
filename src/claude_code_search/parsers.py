# ABOUTME: Message parsing utilities for Claude Code sessions.
# ABOUTME: Extracts structured data from raw JSONL message format.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Commit:
    """A git commit extracted from tool results."""

    commit_hash: str
    commit_message: str
    branch: str | None = None
    timestamp: str | None = None


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
    commit_intent: str | None = None  # Commit message from git commit command


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
    content_type: str  # "text", "tool_use", "tool_result", "thinking", "system"
    tool_summary: str | None = None  # Human-readable summary of tool activity
    cost_usd: float | None = None
    duration_ms: int | None = None
    tool_usages: list[ToolUsage] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)


def parse_message(raw: dict[str, Any], session_id: str, seq: int) -> ParsedMessage:
    """Parse a raw message into structured data."""
    message_id = raw.get("uuid", f"{session_id}-{seq}")
    role = raw.get("message", {}).get("role", raw.get("type", "unknown"))
    timestamp = raw.get("timestamp")
    cost_usd = raw.get("costUSD")
    duration_ms = raw.get("durationMs")
    thinking_content = raw.get("thinking")

    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_usages: list[ToolUsage] = []
    tool_results: list[str] = []
    pending_tools: dict[str, ToolUsage] = {}
    commits: list[Commit] = []

    content = raw.get("message", {}).get("content", [])
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            block_type = block.get("type")

            if block_type == "text":
                text_parts.append(block.get("text", ""))

            elif block_type == "thinking":
                thinking_text = block.get("thinking", "")
                if thinking_text:
                    thinking_parts.append(thinking_text)

            elif block_type == "tool_use":
                tool_id = block.get("id", "")
                command = _extract_command(block)
                tool = ToolUsage(
                    tool_usage_id=tool_id,
                    message_id=message_id,
                    session_id=session_id,
                    tool_name=block.get("name", ""),
                    tool_input=json.dumps(block.get("input", {})),
                    file_path=_extract_file_path(block),
                    command=command,
                    commit_intent=_extract_commit_intent(command),
                )
                pending_tools[tool_id] = tool
                tool_usages.append(tool)

            elif block_type == "tool_result":
                tool_id = block.get("tool_use_id", "")
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    result_parts = []
                    for part in result_content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            result_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            result_parts.append(part)
                    result_content = "\n".join(result_parts)

                # Extract commits from tool result
                result_str = str(result_content)
                result_commits = _extract_commits_from_result(result_str, timestamp)
                commits.extend(result_commits)

                if tool_id in pending_tools:
                    tool = pending_tools[tool_id]
                    tool.tool_result = result_str
                    tool.is_error = block.get("is_error", False)
                # Track tool results for summary
                tool_results.append(result_str[:100] if result_content else "(empty)")

    text_content = "\n".join(text_parts)

    # Combine thinking from top-level field and content blocks
    all_thinking = [thinking_content] if thinking_content else []
    all_thinking.extend(thinking_parts)
    thinking_content = "\n".join(filter(None, all_thinking)) or None

    searchable_text = "\n".join(filter(None, [text_content, thinking_content]))

    # Determine content type and generate tool summary
    content_type, tool_summary = _determine_content_type(
        text_parts, tool_usages, tool_results, thinking_content, raw.get("type", ""), commits
    )

    return ParsedMessage(
        message_id=message_id,
        session_id=session_id,
        sequence_num=seq,
        role=role,
        timestamp=timestamp,
        text_content=text_content,
        thinking_content=thinking_content,
        searchable_text=searchable_text,
        content_type=content_type,
        tool_summary=tool_summary,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        tool_usages=tool_usages,
        commits=commits,
    )


def _extract_file_path(block: dict[str, Any]) -> str | None:
    """Extract file path from tool input."""
    tool_input: dict[str, Any] = block.get("input", {})
    path = tool_input.get("path") or tool_input.get("file_path")
    return str(path) if path is not None else None


def _extract_command(block: dict[str, Any]) -> str | None:
    """Extract command from bash tool input."""
    if block.get("name") == "Bash":
        cmd = block.get("input", {}).get("command")
        return str(cmd) if cmd is not None else None
    return None


def _extract_commit_intent(command: str | None) -> str | None:
    """Extract commit message from git commit command."""
    if not command:
        return None

    # Match: git commit -m "message" or git commit -m 'message'
    match = re.search(r'git\s+commit\s+.*?-m\s+["\']([^"\']+)["\']', command)
    if match:
        return match.group(1)

    return None


def _extract_commits_from_result(result_content: str, timestamp: str | None = None) -> list[Commit]:
    """Extract commit information from tool result content.

    Matches patterns like:
    - [main a6ab2d7] fix: commit message
    - [detached HEAD 9a8b7c6] test: message
    """
    commits = []

    # Pattern: [branch commit_hash] commit message
    pattern = r"\[([\w\s/-]+)\s+([0-9a-f]{7,40})\]\s+(.+?)(?:\n|$)"

    for match in re.finditer(pattern, result_content):
        branch = match.group(1).strip()
        commit_hash = match.group(2).strip()
        commit_message = match.group(3).strip()

        commits.append(
            Commit(
                commit_hash=commit_hash,
                commit_message=commit_message,
                branch=branch,
                timestamp=timestamp,
            )
        )

    return commits


def _determine_content_type(
    text_parts: list[str],
    tool_usages: list[ToolUsage],
    tool_results: list[str],
    thinking_content: str | None,
    raw_type: str,
    commits: list[Commit],
) -> tuple[str, str | None]:
    """Determine the content type and generate a tool summary."""
    has_text = any(part.strip() for part in text_parts)

    # System message types
    if raw_type in ("file-history-snapshot", "summary"):
        return ("system", None)

    # Tool result messages (user messages containing tool results)
    if tool_results:
        summary_parts = []
        for result in tool_results[:3]:  # Limit to first 3 results
            preview = result[:80].replace("\n", " ").strip()
            if len(result) > 80:
                preview += "..."
            summary_parts.append(preview)

        # Add commit info to summary if present
        if commits:
            commit_info = ", ".join(f"commit {c.commit_hash}" for c in commits[:2])
            summary_parts.append(commit_info)

        tool_summary = "; ".join(summary_parts)
        if has_text:
            return ("text", tool_summary)
        return ("tool_result", tool_summary)

    # Tool use messages (assistant messages invoking tools)
    if tool_usages:
        summary_parts = []
        for tool in tool_usages[:3]:  # Limit to first 3 tools
            if tool.file_path:
                summary_parts.append(f"{tool.tool_name}: {tool.file_path}")
            elif tool.command:
                cmd_preview = tool.command[:50]
                if len(tool.command) > 50:
                    cmd_preview += "..."
                summary_parts.append(f"Bash: {cmd_preview}")
            else:
                summary_parts.append(tool.tool_name)
        tool_summary = " | ".join(summary_parts)
        if has_text:
            return ("text", tool_summary)
        return ("tool_use", tool_summary)

    # Thinking-only messages
    if thinking_content and not has_text:
        thinking_preview = thinking_content[:80].replace("\n", " ").strip()
        if len(thinking_content) > 80:
            thinking_preview += "..."
        return ("thinking", thinking_preview)

    # Regular text messages
    return ("text", None)
