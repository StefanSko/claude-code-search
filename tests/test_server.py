# ABOUTME: Tests for the FastAPI server and API endpoints.
# ABOUTME: Verifies search, session, and statistics API functionality.

import pytest
from fastapi.testclient import TestClient

from claude_code_search.index import SearchIndex
from claude_code_search.server.app import create_app


@pytest.fixture
def client(indexed_search: SearchIndex) -> TestClient:
    """Create a test client with indexed data."""
    app = create_app(indexed_search)
    return TestClient(app)


class TestAPIEndpoints:
    """Tests for the API endpoints."""

    def test_root_returns_html(self, client: TestClient) -> None:
        """Root endpoint returns HTML page."""
        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_get_stats(self, client: TestClient) -> None:
        """Stats endpoint returns index statistics."""
        response = client.get("/api/stats")

        assert response.status_code == 200
        data = response.json()
        assert "session_count" in data
        assert "message_count" in data
        assert data["session_count"] == 1

    def test_list_sessions(self, client: TestClient) -> None:
        """Sessions endpoint returns list of sessions."""
        response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "test-session-001"

    def test_get_session(self, client: TestClient) -> None:
        """Get specific session by ID."""
        response = client.get("/api/sessions/test-session-001")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session-001"
        assert "messages" in data

    def test_search(self, client: TestClient) -> None:
        """Search endpoint returns matching results."""
        response = client.get("/api/search", params={"q": "Python"})

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total" in data
        assert data["query"] == "Python"
        assert len(data["results"]) > 0

    def test_search_with_role_filter(self, client: TestClient) -> None:
        """Search with role filter."""
        response = client.get("/api/search", params={"q": "CLI", "role": "user"})

        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["role"] == "user"

    def test_search_requires_query(self, client: TestClient) -> None:
        """Search requires query parameter."""
        response = client.get("/api/search")

        assert response.status_code == 422

    def test_get_message(self, client: TestClient) -> None:
        """Get specific message by ID."""
        response = client.get("/api/messages/msg-001")

        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == "msg-001"

    def test_get_message_with_context(self, client: TestClient) -> None:
        """Get message with surrounding context."""
        response = client.get("/api/messages/msg-002/context", params={"before": 1, "after": 1})

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "context" in data
        assert len(data["context"]) >= 2

    def test_search_tools(self, client: TestClient) -> None:
        """Search within tool usages."""
        response = client.get("/api/search/tools", params={"q": "cli.py"})

        assert response.status_code == 200
        data = response.json()
        assert "results" in data


class TestAPIEdgeCases:
    """Tests for API edge cases and error handling."""

    def test_get_nonexistent_session(self, client: TestClient) -> None:
        """Get non-existent session returns null."""
        response = client.get("/api/sessions/nonexistent")

        assert response.status_code == 200
        assert response.json() is None

    def test_get_nonexistent_message(self, client: TestClient) -> None:
        """Get non-existent message returns null."""
        response = client.get("/api/messages/nonexistent")

        assert response.status_code == 200
        assert response.json() is None

    def test_search_no_results(self, client: TestClient) -> None:
        """Search with no matches returns empty results."""
        response = client.get("/api/search", params={"q": "xyznonexistent123"})

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["total"] == 0

    def test_search_limit(self, client: TestClient) -> None:
        """Search respects limit parameter."""
        response = client.get("/api/search", params={"q": "CLI", "limit": 1})

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 1
