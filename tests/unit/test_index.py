from __future__ import annotations

from claude_code_search.index import SearchIndex


def test_index_and_search(sample_session_messages: list[dict]) -> None:
    index = SearchIndex(":memory:")
    index.index_session(
        session_id="session-123",
        messages=sample_session_messages,
        source="local",
        session_path="/tmp/session-123/messages.jsonl",
    )

    stats = index.get_stats()
    assert stats["session_count"] == 1
    assert stats["message_count"] == 3
    assert stats["tool_count"] == 2

    results = index.search(query="CLI")
    assert results
    assert results[0]["session_id"] == "session-123"

    message = index.get_message("msg-002")
    assert message
    assert message["role"] == "assistant"


def test_message_context(sample_session_messages: list[dict]) -> None:
    index = SearchIndex(":memory:")
    index.index_session(
        session_id="session-123",
        messages=sample_session_messages,
        source="local",
        session_path="/tmp/session-123/messages.jsonl",
    )

    context = index.get_message_with_context("msg-002", before=1, after=1)
    assert context["message"]["message_id"] == "msg-002"
    assert len(context["before"]) == 1
    assert len(context["after"]) == 1
