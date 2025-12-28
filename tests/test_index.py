# ABOUTME: Tests for the DuckDB search index functionality.
# ABOUTME: Verifies indexing, searching, and statistics operations.


from claude_code_search.index import SearchIndex


class TestSearchIndex:
    """Tests for the SearchIndex class."""

    def test_is_empty_on_new_index(self, search_index: SearchIndex) -> None:
        """New index should be empty."""
        assert search_index.is_empty()

    def test_is_not_empty_after_indexing(self, indexed_search: SearchIndex) -> None:
        """Index should not be empty after adding sessions."""
        assert not indexed_search.is_empty()

    def test_index_session(self, search_index: SearchIndex, sample_messages: list[dict]) -> None:
        """Index a session and verify it's stored."""
        search_index.index_session(
            session_id="test-session",
            messages=sample_messages,
            source="local",
            project_directory="my-project",
        )

        sessions = search_index.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "test-session"
        assert sessions[0]["project_directory"] == "my-project"

    def test_get_stats(self, indexed_search: SearchIndex) -> None:
        """Get statistics from indexed data."""
        stats = indexed_search.get_stats()

        assert stats["session_count"] == 1
        assert stats["message_count"] == 5
        assert stats["tool_count"] > 0
        assert stats["total_cost_usd"] > 0

    def test_search_returns_results(self, indexed_search: SearchIndex) -> None:
        """Search should return matching results."""
        results = indexed_search.search("Python CLI")

        assert len(results) > 0
        assert any("Python" in str(r.get("text_content", "")) for r in results)

    def test_search_with_role_filter(self, indexed_search: SearchIndex) -> None:
        """Search with role filter."""
        results = indexed_search.search("CLI", role="user")

        assert all(r["role"] == "user" for r in results)

    def test_search_returns_empty_for_no_match(self, indexed_search: SearchIndex) -> None:
        """Search should return empty for non-matching query."""
        results = indexed_search.search("xyznonexistent123")

        assert len(results) == 0

    def test_get_session(self, indexed_search: SearchIndex) -> None:
        """Get a specific session by ID."""
        session = indexed_search.get_session("test-session-001")

        assert session is not None
        assert session["session_id"] == "test-session-001"
        assert "messages" in session
        assert len(session["messages"]) == 5

    def test_get_session_not_found(self, indexed_search: SearchIndex) -> None:
        """Get non-existent session returns None."""
        session = indexed_search.get_session("nonexistent")

        assert session is None

    def test_get_message(self, indexed_search: SearchIndex) -> None:
        """Get a specific message by ID."""
        message = indexed_search.get_message("msg-001")

        assert message is not None
        assert message["message_id"] == "msg-001"
        assert message["role"] == "user"

    def test_get_message_with_context(self, indexed_search: SearchIndex) -> None:
        """Get a message with surrounding context."""
        result = indexed_search.get_message_with_context("msg-002", before=1, after=1)

        assert result is not None
        assert result["message"]["message_id"] == "msg-002"
        assert len(result["context"]) >= 2

    def test_list_sessions(self, indexed_search: SearchIndex) -> None:
        """List all indexed sessions."""
        sessions = indexed_search.list_sessions()

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "test-session-001"


class TestSearchIndexMultipleSessions:
    """Tests for index with multiple sessions."""

    def test_index_multiple_sessions(
        self, search_index: SearchIndex, sample_messages: list[dict]
    ) -> None:
        """Index multiple sessions."""
        search_index.index_session("session-1", sample_messages, "local")
        search_index.index_session("session-2", sample_messages[:2], "local")

        stats = search_index.get_stats()
        assert stats["session_count"] == 2

    def test_search_across_sessions(self, search_index: SearchIndex) -> None:
        """Search should find results across all sessions."""
        messages_1 = [
            {"uuid": "s1-msg-1", "message": {"role": "user", "content": "Create Python CLI"}}
        ]
        messages_2 = [
            {"uuid": "s2-msg-1", "message": {"role": "user", "content": "Build Python server"}}
        ]
        search_index.index_session("session-1", messages_1, "local")
        search_index.index_session("session-2", messages_2, "local")

        results = search_index.search("Python", limit=100)

        session_ids = {r["session_id"] for r in results}
        assert len(session_ids) == 2


class TestContentTypeFilter:
    """Tests for content_type filtering in search."""

    def test_search_with_content_type_text(self, search_index: SearchIndex) -> None:
        """Filter search results by content_type='text'."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Python code"}},
            {
                "uuid": "msg-2",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Write",
                            "input": {"path": "python.py"},
                        },
                    ],
                },
            },
        ]
        search_index.index_session("session-1", messages, "local")

        results = search_index.search("Python", content_type="text")

        assert len(results) == 1
        assert results[0]["content_type"] == "text"

    def test_search_with_content_type_tool(self, search_index: SearchIndex) -> None:
        """Filter search results by content_type='tool' (matches tool_use and tool_result)."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Create CLI tool"}},
            {
                "uuid": "msg-2",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "npm install"},
                        },
                    ],
                },
                # Add thinking content so it's searchable
                "thinking": "I need to run the CLI command",
            },
            {
                "uuid": "msg-3",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "Installed"},
                        # Add text so it appears in search
                        {"type": "text", "text": "CLI tool installed successfully"},
                    ],
                },
            },
        ]
        search_index.index_session("session-1", messages, "local")

        # Search for CLI - msg-2 has it in thinking, msg-3 has it in text
        results = search_index.search("CLI", content_type="tool")

        # Only msg-2 has content_type='tool_use' (msg-3 has text so it's 'text' type)
        assert len(results) >= 1
        assert all(r["content_type"] in ("tool_use", "tool_result") for r in results)


class TestContextWithToolSummary:
    """Tests for message context including tool_summary."""

    def test_context_includes_content_type(self, indexed_search: SearchIndex) -> None:
        """Context messages should include content_type field."""
        result = indexed_search.get_message_with_context("msg-002", before=1, after=1)

        assert result is not None
        for msg in result["context"]:
            assert "content_type" in msg

    def test_context_includes_tool_summary(self, indexed_search: SearchIndex) -> None:
        """Context messages with tools should include tool_summary field."""
        result = indexed_search.get_message_with_context("msg-002", before=1, after=1)

        assert result is not None
        # msg-002 has a Write tool, should have tool_summary
        target = result["message"]
        assert target["tool_summary"] is not None
        assert "Write" in target["tool_summary"]

    def test_context_boundary_first_message(self, indexed_search: SearchIndex) -> None:
        """Context for first message should only have 'next' messages."""
        result = indexed_search.get_message_with_context("msg-001", before=2, after=2)

        assert result is not None
        context_seqs = [m["sequence_num"] for m in result["context"]]
        # First message is seq=0, should have 0, 1, 2 (no negative sequences)
        assert min(context_seqs) == 0
        assert 0 in context_seqs

    def test_context_boundary_last_message(self, indexed_search: SearchIndex) -> None:
        """Context for last message should only have 'prev' messages."""
        result = indexed_search.get_message_with_context("msg-005", before=2, after=2)

        assert result is not None
        context_seqs = [m["sequence_num"] for m in result["context"]]
        # Last message is seq=4, should have 2, 3, 4 (no seq > 4)
        assert max(context_seqs) == 4
        assert 4 in context_seqs

    def test_context_target_always_included(self, indexed_search: SearchIndex) -> None:
        """Target message should always be in context list."""
        for msg_id in ["msg-001", "msg-002", "msg-003", "msg-004", "msg-005"]:
            result = indexed_search.get_message_with_context(msg_id, before=1, after=1)

            assert result is not None
            context_ids = [m["message_id"] for m in result["context"]]
            assert msg_id in context_ids
