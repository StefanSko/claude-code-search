# ABOUTME: FastAPI application for the Claude Code Search web UI.
# ABOUTME: Provides REST API endpoints and serves the single-page frontend.

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse

from claude_code_search.index import SearchIndex

STATIC_DIR = Path(__file__).parent.parent / "static"

_index: SearchIndex | None = None


def get_index() -> SearchIndex:
    """Get the current search index."""
    if _index is None:
        raise RuntimeError("Search index not initialized")
    return _index


def create_app(index: SearchIndex) -> FastAPI:
    """Create and configure the FastAPI application."""
    global _index
    _index = index

    app = FastAPI(
        title="Claude Code Search",
        description="Search across Claude Code sessions",
        version="0.1.0",
    )

    @app.get("/", response_class=HTMLResponse)
    async def root() -> FileResponse:
        """Serve the main HTML page."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/stats")
    async def get_stats() -> dict[str, Any]:
        """Get index statistics."""
        return get_index().get_stats()

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        """List all indexed sessions."""
        return get_index().list_sessions()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any] | None:
        """Get a single session with all messages."""
        return get_index().get_session(session_id)

    @app.get("/api/search")
    async def search(
        q: str = Query(..., min_length=1, description="Search query"),
        role: str | None = Query(None, description="Filter by role (user/assistant)"),
        tool: str | None = Query(None, description="Filter by tool name"),
        session: str | None = Query(None, description="Filter by session ID"),
        since: str | None = Query(None, description="Messages after this date"),
        until: str | None = Query(None, description="Messages before this date"),
        content_type: str | None = Query(
            None, description="Filter by content type (text/tool/tool_use/tool_result)"
        ),
        limit: int = Query(20, ge=1, le=100, description="Max results"),
    ) -> dict[str, Any]:
        """Full-text search with filters."""
        results = get_index().search(
            query=q,
            role=role,
            tool=tool,
            session_id=session,
            since=since,
            until=until,
            content_type=content_type,
            limit=limit,
        )
        return {
            "results": results,
            "total": len(results),
            "query": q,
        }

    @app.get("/api/search/tools")
    async def search_tools(
        q: str = Query(..., min_length=1, description="Search query"),
        tool_name: str | None = Query(None, description="Filter by tool name"),
        limit: int = Query(20, ge=1, le=100, description="Max results"),
    ) -> dict[str, Any]:
        """Search within tool usages."""
        results = get_index().search_tools(query=q, tool_name=tool_name, limit=limit)
        return {
            "results": results,
            "total": len(results),
            "query": q,
        }

    @app.get("/api/messages/{message_id}")
    async def get_message(message_id: str) -> dict[str, Any] | None:
        """Get a single message with tool usages."""
        return get_index().get_message(message_id)

    @app.get("/api/messages/{message_id}/context")
    async def get_message_context(
        message_id: str,
        before: int = Query(2, ge=0, le=10, description="Messages before"),
        after: int = Query(2, ge=0, le=10, description="Messages after"),
    ) -> dict[str, Any] | None:
        """Get a message with surrounding context."""
        return get_index().get_message_with_context(message_id, before, after)

    @app.get("/api/interactions/{session_id}")
    async def get_interactions(
        session_id: str,
        limit: int | None = Query(None, ge=1, le=1000, description="Max interactions"),
    ) -> list[dict[str, Any]]:
        """Get all interactions for a session."""
        return get_index().get_interactions(session_id, limit)

    @app.get("/api/interaction/{interaction_id}")
    async def get_interaction(interaction_id: str) -> dict[str, Any] | None:
        """Get a single interaction with all messages and commits."""
        return get_index().get_interaction(interaction_id)

    @app.get("/api/search/interactions")
    async def search_interactions(
        q: str = Query(..., min_length=1, description="Search query"),
        session: str | None = Query(None, description="Filter by session ID"),
        limit: int = Query(20, ge=1, le=100, description="Max results"),
    ) -> dict[str, Any]:
        """Search for interactions matching the query."""
        results = get_index().search_interactions(query=q, session_id=session, limit=limit)
        return {
            "results": results,
            "total": len(results),
            "query": q,
        }

    @app.get("/api/commits/{commit_hash}")
    async def get_commit(commit_hash: str) -> dict[str, Any] | None:
        """Get commit details by hash."""
        return get_index().get_commit(commit_hash)

    @app.get("/api/search/commits")
    async def search_commits(
        q: str = Query(..., min_length=1, description="Search query"),
        session: str | None = Query(None, description="Filter by session ID"),
        limit: int = Query(20, ge=1, le=100, description="Max results"),
    ) -> dict[str, Any]:
        """Search commits by hash or message."""
        results = get_index().search_commits(query=q, session_id=session, limit=limit)
        return {
            "results": results,
            "total": len(results),
            "query": q,
        }

    return app


def run_server(
    index: SearchIndex,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Start the web server with the given index."""
    app = create_app(index)

    if open_browser:
        webbrowser.open(f"http://{host}:{port}")

    uvicorn.run(app, host=host, port=port, log_level="warning")
