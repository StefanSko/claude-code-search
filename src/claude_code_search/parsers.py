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


@dataclass
class Interaction:
    """A grouped user-assistant exchange with all related messages."""

    interaction_id: str
    session_id: str
    sequence_num: int  # Order within session
    user_prompt: str  # The user's question/request
    message_ids: list[str]  # All messages in this interaction
    timestamp: str | None  # Timestamp of first message
    has_thinking: bool = False
    tool_calls: list[str] = field(default_factory=list)  # Tool names used
    commits: list[Commit] = field(default_factory=list)
    match_locations: list[dict[str, str]] = field(
        default_factory=list
    )  # Where search matches occurred
    total_cost_usd: float = 0.0


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
    """Extract commit message from git commit command.

    Handles various formats:
    - git commit -m "message"
    - git commit -m 'message'
    - git commit -m "$(cat <<'EOF'\nmessage\nEOF\n)"
    """
    if not command:
        return None

    # First try: HEREDOC style - git commit -m "$(cat <<'EOF'\nmessage\nEOF\n)"
    # This is common in Claude Code commits
    heredoc_match = re.search(
        r'git\s+commit\s+.*?-m\s+"\$\(cat\s+<<[\'"]?EOF[\'"]?\s*\n(.+?)\n\s*EOF',
        command,
        re.DOTALL,
    )
    if heredoc_match:
        # Extract the first line of the commit message (the title)
        message = heredoc_match.group(1).strip()
        # Return just the first line if there are multiple
        first_line = message.split("\n")[0].strip()
        return first_line if first_line else message

    # Second try: Simple quoted message - git commit -m "message" or -m 'message'
    simple_match = re.search(r'git\s+commit\s+.*?-m\s+["\']([^"\']+)["\']', command)
    if simple_match:
        return simple_match.group(1)

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


def group_messages_into_interactions(
    messages: list[dict[str, Any]], session_id: str
) -> list[Interaction]:
    """Group raw messages into logical user-assistant interactions.

    An interaction consists of:
    1. A user message (prompt)
    2. An assistant response (with optional thinking)
    3. All tool uses from the assistant
    4. All tool results (user messages) that follow

    The interaction ends when the next user prompt appears (non-tool-result message).
    """
    interactions: list[Interaction] = []
    current_messages: list[ParsedMessage] = []
    interaction_num = 0

    for seq, raw_msg in enumerate(messages):
        parsed = parse_message(raw_msg, session_id, seq)
        role = parsed.role

        # Check if this is a user prompt (not a tool result)
        is_user_prompt = role == "user" and parsed.content_type not in (
            "tool_result",
            "system",
        )

        # Start a new interaction if we see a user prompt and have accumulated messages
        if is_user_prompt and current_messages:
            # Finalize the previous interaction
            interaction = _create_interaction(current_messages, session_id, interaction_num)
            interactions.append(interaction)
            interaction_num += 1
            current_messages = []

        # Add message to current interaction
        current_messages.append(parsed)

    # Don't forget the last interaction
    if current_messages:
        interaction = _create_interaction(current_messages, session_id, interaction_num)
        interactions.append(interaction)

    return interactions


def _create_interaction(
    messages: list[ParsedMessage], session_id: str, sequence_num: int
) -> Interaction:
    """Create an Interaction from a list of messages."""
    # Extract user prompt (first user message or empty if starts with assistant)
    user_prompt = ""
    for msg in messages:
        if msg.role == "user" and msg.content_type not in ("tool_result", "system"):
            user_prompt = msg.text_content
            break

    # Collect metadata
    message_ids = [msg.message_id for msg in messages]
    timestamp = messages[0].timestamp if messages else None
    has_thinking = any(msg.thinking_content for msg in messages)

    # Collect tool calls (unique tool names)
    tool_calls: list[str] = []
    seen_tools: set[str] = set()
    for msg in messages:
        for tool in msg.tool_usages:
            if tool.tool_name not in seen_tools:
                tool_calls.append(tool.tool_name)
                seen_tools.add(tool.tool_name)

    # Collect all commits
    commits: list[Commit] = []
    for msg in messages:
        commits.extend(msg.commits)

    # Calculate total cost
    total_cost = sum(msg.cost_usd or 0.0 for msg in messages)

    return Interaction(
        interaction_id=f"{session_id}-interaction-{sequence_num}",
        session_id=session_id,
        sequence_num=sequence_num,
        user_prompt=user_prompt,
        message_ids=message_ids,
        timestamp=timestamp,
        has_thinking=has_thinking,
        tool_calls=tool_calls,
        commits=commits,
        total_cost_usd=total_cost,
    )
