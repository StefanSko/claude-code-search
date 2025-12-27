# ABOUTME: Tests for message parsing functionality.
# ABOUTME: Verifies extraction of text, tools, and metadata from raw messages.


from claude_code_search.parsers import parse_message


class TestParseMessage:
    """Tests for the parse_message function."""

    def test_parse_simple_user_message(self) -> None:
        """Parse a simple user text message."""
        raw = {
            "uuid": "msg-001",
            "type": "user",
            "message": {"role": "user", "content": "Hello, world!"},
            "timestamp": "2024-12-25T10:00:00Z",
        }

        result = parse_message(raw, "session-1", 0)

        assert result.message_id == "msg-001"
        assert result.session_id == "session-1"
        assert result.sequence_num == 0
        assert result.role == "user"
        assert result.text_content == "Hello, world!"
        assert result.searchable_text == "Hello, world!"
        assert result.tool_usages == []

    def test_parse_assistant_message_with_tool(self) -> None:
        """Parse an assistant message with tool usage."""
        raw = {
            "uuid": "msg-002",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll create the file."},
                    {
                        "type": "tool_use",
                        "id": "tool-001",
                        "name": "Write",
                        "input": {"path": "test.py", "content": "# test"},
                    },
                ],
            },
            "timestamp": "2024-12-25T10:00:05Z",
            "costUSD": 0.02,
            "durationMs": 1500,
            "thinking": "I need to create a file.",
        }

        result = parse_message(raw, "session-1", 1)

        assert result.message_id == "msg-002"
        assert result.role == "assistant"
        assert result.text_content == "I'll create the file."
        assert result.thinking_content == "I need to create a file."
        assert result.cost_usd == 0.02
        assert result.duration_ms == 1500
        assert len(result.tool_usages) == 1
        assert result.tool_usages[0].tool_name == "Write"
        assert result.tool_usages[0].file_path == "test.py"

    def test_parse_message_with_tool_result(self) -> None:
        """Parse a message containing tool results."""
        raw = {
            "uuid": "msg-003",
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-001",
                        "content": "File created successfully",
                    }
                ],
            },
            "timestamp": "2024-12-25T10:00:10Z",
        }

        result = parse_message(raw, "session-1", 2)

        assert result.message_id == "msg-003"
        assert result.text_content == ""

    def test_parse_message_generates_id_if_missing(self) -> None:
        """Generate a message ID if not provided."""
        raw = {
            "type": "user",
            "message": {"role": "user", "content": "test"},
        }

        result = parse_message(raw, "session-1", 5)

        assert result.message_id == "session-1-5"

    def test_searchable_text_includes_thinking(self) -> None:
        """Searchable text should include thinking content."""
        raw = {
            "uuid": "msg-004",
            "message": {"role": "assistant", "content": "Response text"},
            "thinking": "Internal reasoning",
        }

        result = parse_message(raw, "session-1", 0)

        assert "Response text" in result.searchable_text
        assert "Internal reasoning" in result.searchable_text
