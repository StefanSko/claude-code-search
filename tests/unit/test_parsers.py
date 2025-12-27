from __future__ import annotations

from claude_code_search.parsers import parse_message


def test_parse_message_extracts_text_and_tools(sample_session_messages: list[dict]) -> None:
    message, tool_usages = parse_message(sample_session_messages[1], "session-123", 1)

    assert message["message_id"] == "msg-002"
    assert message["role"] == "assistant"
    assert "CLI using Click" in message["text_content"]
    assert "file search CLI" in message["thinking_content"]
    assert "file search CLI" in message["searchable_text"]

    assert len(tool_usages) == 2
    bash_tool = next(tu for tu in tool_usages if tu["tool_name"] == "bash")
    assert bash_tool["command"] == "ls -la"
    assert bash_tool["tool_result"].startswith("total")

    write_tool = next(tu for tu in tool_usages if tu["tool_name"] == "write")
    assert write_tool["file_path"] == "cli.py"
    assert write_tool["tool_result"] == "File written successfully"
