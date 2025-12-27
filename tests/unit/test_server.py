from __future__ import annotations

from fastapi.testclient import TestClient

from claude_code_search.index import SearchIndex
from claude_code_search.server.app import create_app


def test_server_stats_endpoint(sample_session_messages: list[dict]) -> None:
    index = SearchIndex(":memory:")
    index.index_session(
        session_id="session-123",
        messages=sample_session_messages,
        source="local",
        session_path="/tmp/session-123/messages.jsonl",
    )

    app = create_app(index)
    client = TestClient(app)

    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["session_count"] == 1
    assert data["message_count"] == 3


def test_server_search_endpoint(sample_session_messages: list[dict]) -> None:
    index = SearchIndex(":memory:")
    index.index_session(
        session_id="session-123",
        messages=sample_session_messages,
        source="local",
        session_path="/tmp/session-123/messages.jsonl",
    )

    app = create_app(index)
    client = TestClient(app)

    response = client.get("/api/search", params={"q": "Click"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["results"][0]["session_id"] == "session-123"
