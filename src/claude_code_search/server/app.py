from __future__ import annotations

import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from ..formatters import format_results
from ..index import SearchIndex

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(search_index: SearchIndex) -> FastAPI:
    app = FastAPI(title="Claude Code Search")
    app.state.index = search_index

    @app.get("/", response_class=FileResponse)
    async def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/stats")
    async def get_stats() -> dict[str, object]:
        return app.state.index.get_stats()

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, object]]:
        return app.state.index.list_sessions()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, object]:
        session = app.state.index.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @app.get("/api/messages/{message_id}")
    async def get_message(message_id: str) -> dict[str, object]:
        message = app.state.index.get_message(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        return message

    @app.get("/api/messages/{message_id}/context")
    async def get_message_context(
        message_id: str,
        before: int = Query(2, ge=0, le=10),
        after: int = Query(2, ge=0, le=10),
    ) -> dict[str, object]:
        return app.state.index.get_message_with_context(message_id, before=before, after=after)

    @app.get("/api/search")
    async def search(
        q: str = Query(..., min_length=1),
        role: str | None = Query(None),
        tool: str | None = Query(None),
        session: str | None = Query(None),
        since: str | None = Query(None),
        until: str | None = Query(None),
        limit: int = Query(20, ge=1, le=100),
    ) -> dict[str, object]:
        results = app.state.index.search(
            query=q,
            role=role,
            tool=tool,
            session_id=session,
            since=since,
            until=until,
            limit=limit,
        )
        return {
            "results": results,
            "total": len(results),
            "query": q,
        }

    @app.get("/api/export")
    async def export_results(
        q: str = Query(..., min_length=1),
        format: str = Query("json", pattern="^(json|csv)$"),
        role: str | None = Query(None),
        tool: str | None = Query(None),
        session: str | None = Query(None),
        since: str | None = Query(None),
        until: str | None = Query(None),
    ) -> object:
        results = app.state.index.search(
            query=q,
            role=role,
            tool=tool,
            session_id=session,
            since=since,
            until=until,
            limit=1000,
        )
        if format == "csv":
            csv_payload = format_results(results, "csv") or ""
            return PlainTextResponse(csv_payload, media_type="text/csv")
        return results

    return app


def run_server(search_index: SearchIndex, host: str, port: int, open_browser: bool) -> None:
    app = create_app(search_index)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
