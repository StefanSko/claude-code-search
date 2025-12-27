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


class TestContentTypeDetection:
    """Tests for content_type and tool_summary functionality."""

    def test_text_message_content_type(self) -> None:
        """Simple text message should have content_type='text'."""
        raw = {
            "uuid": "msg-001",
            "message": {"role": "user", "content": "Hello, world!"},
        }

        result = parse_message(raw, "session-1", 0)

        assert result.content_type == "text"
        assert result.tool_summary is None

    def test_tool_use_only_message_content_type(self) -> None:
        """Message with only tool_use should have content_type='tool_use'."""
        raw = {
            "uuid": "msg-002",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-001",
                        "name": "Write",
                        "input": {"path": "test.py", "content": "# test"},
                    },
                ],
            },
        }

        result = parse_message(raw, "session-1", 1)

        assert result.content_type == "tool_use"
        assert result.tool_summary is not None
        assert "Write" in result.tool_summary
        assert "test.py" in result.tool_summary

    def test_tool_result_message_content_type(self) -> None:
        """Message with tool_result should have content_type='tool_result'."""
        raw = {
            "uuid": "msg-003",
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
        }

        result = parse_message(raw, "session-1", 2)

        assert result.content_type == "tool_result"
        assert result.tool_summary is not None
        assert "File created successfully" in result.tool_summary

    def test_thinking_only_message_content_type(self) -> None:
        """Message with only thinking block should have content_type='thinking'."""
        raw = {
            "uuid": "msg-004",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me analyze this problem..."},
                ],
            },
        }

        result = parse_message(raw, "session-1", 3)

        assert result.content_type == "thinking"
        assert result.tool_summary is not None
        assert "analyze" in result.tool_summary

    def test_system_message_content_type(self) -> None:
        """System messages like file-history-snapshot should have content_type='system'."""
        raw = {
            "uuid": "msg-005",
            "type": "file-history-snapshot",
            "message": {"role": "file-history-snapshot", "content": []},
        }

        result = parse_message(raw, "session-1", 4)

        assert result.content_type == "system"

    def test_text_with_tool_has_text_type_but_tool_summary(self) -> None:
        """Message with text AND tool should be 'text' type but have tool_summary."""
        raw = {
            "uuid": "msg-006",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll create the file for you."},
                    {
                        "type": "tool_use",
                        "id": "tool-001",
                        "name": "Write",
                        "input": {"path": "cli.py", "content": "# cli"},
                    },
                ],
            },
        }

        result = parse_message(raw, "session-1", 5)

        assert result.content_type == "text"
        assert result.tool_summary is not None
        assert "Write" in result.tool_summary
        assert "cli.py" in result.tool_summary

    def test_bash_command_in_tool_summary(self) -> None:
        """Bash tool usage should show command preview in summary."""
        raw = {
            "uuid": "msg-007",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-001",
                        "name": "Bash",
                        "input": {"command": "npm install && npm test"},
                    },
                ],
            },
        }

        result = parse_message(raw, "session-1", 6)

        assert result.content_type == "tool_use"
        assert "Bash" in result.tool_summary
        assert "npm install" in result.tool_summary

    def test_multiple_tools_in_summary(self) -> None:
        """Multiple tool usages should all appear in summary."""
        raw = {
            "uuid": "msg-008",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-001",
                        "name": "Read",
                        "input": {"file_path": "config.py"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tool-002",
                        "name": "Write",
                        "input": {"path": "output.py", "content": "# out"},
                    },
                ],
            },
        }

        result = parse_message(raw, "session-1", 7)

        assert result.content_type == "tool_use"
        assert "Read" in result.tool_summary
        assert "Write" in result.tool_summary


class TestThinkingExtraction:
    """Tests for thinking content extraction from various sources."""

    def test_thinking_from_top_level_field(self) -> None:
        """Extract thinking from top-level 'thinking' field."""
        raw = {
            "uuid": "msg-001",
            "message": {"role": "assistant", "content": "Response"},
            "thinking": "Top-level thinking content",
        }

        result = parse_message(raw, "session-1", 0)

        assert result.thinking_content is not None
        assert "Top-level thinking" in result.thinking_content

    def test_thinking_from_content_block(self) -> None:
        """Extract thinking from content block with type='thinking'."""
        raw = {
            "uuid": "msg-002",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Block thinking content"},
                ],
            },
        }

        result = parse_message(raw, "session-1", 1)

        assert result.thinking_content is not None
        assert "Block thinking" in result.thinking_content

    def test_combined_thinking_sources(self) -> None:
        """Combine thinking from both top-level field and content blocks."""
        raw = {
            "uuid": "msg-003",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Response text"},
                    {"type": "thinking", "thinking": "Block thinking"},
                ],
            },
            "thinking": "Top-level thinking",
        }

        result = parse_message(raw, "session-1", 2)

        assert result.thinking_content is not None
        assert "Top-level thinking" in result.thinking_content
        assert "Block thinking" in result.thinking_content

    def test_thinking_included_in_searchable_text(self) -> None:
        """Thinking from content blocks should be in searchable_text."""
        raw = {
            "uuid": "msg-004",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Unique searchable phrase"},
                ],
            },
        }

        result = parse_message(raw, "session-1", 3)

        assert "Unique searchable phrase" in result.searchable_text
