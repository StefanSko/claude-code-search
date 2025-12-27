# ABOUTME: Tests for the DuckDB search index functionality.
# ABOUTME: Verifies indexing, searching, and statistics operations.


from claude_code_search.index import SearchIndex


class TestSearchIndex:
    """Tests for the SearchIndex class."""

    def test_is_empty_on_new_index(self, search_index: SearchIndex) -> None:
        """New index should be empty."""
        assert search_index.is_empty()

    def test_is_not_empty_after_indexing(
        self, indexed_search: SearchIndex
    ) -> None:
        """Index should not be empty after adding sessions."""
        assert not indexed_search.is_empty()

    def test_index_session(
        self, search_index: SearchIndex, sample_messages: list[dict]
    ) -> None:
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

    def test_search_returns_empty_for_no_match(
        self, indexed_search: SearchIndex
    ) -> None:
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
        result = indexed_search.get_message_with_context(
            "msg-002", before=1, after=1
        )

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

    def test_search_across_sessions(
        self, search_index: SearchIndex
    ) -> None:
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
