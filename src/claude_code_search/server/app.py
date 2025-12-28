from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any, cast

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
        interactions = _group_results_by_interaction(app.state.index, results)
        session_groups = _group_results_by_session(app.state.index, interactions)
        return {
            "results": results,
            "total": len(results),
            "query": q,
            "interactions": interactions,
            "sessions": session_groups,
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

    @app.get("/api/sessions/{session_id}/interactions/{interaction_id}")
    async def get_interaction(session_id: str, interaction_id: str) -> dict[str, object]:
        try:
            return app.state.index.get_interaction(session_id, interaction_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Interaction not found")

    return app


def _group_results_by_interaction(
    search_index: SearchIndex, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sessions = {str(result["session_id"]) for result in results}
    interaction_maps: dict[str, dict[str, Any]] = {}
    message_to_interaction: dict[str, str] = {}

    for session_id in sessions:
        messages = search_index.list_messages(session_id)
        interactions, message_map = _build_interaction_index(messages)
        for interaction in interactions:
            interaction_id = str(interaction["interaction_id"])
            interaction_maps[interaction_id] = interaction
        message_to_interaction.update(message_map)

    for result in results:
        interaction_id = message_to_interaction.get(str(result["message_id"]))
        if not interaction_id:
            continue
        interaction = interaction_maps.get(interaction_id)
        if interaction is None:
            continue
        matches = cast(list[dict[str, Any]], interaction.setdefault("matches", []))
        matches.append(_build_match_preview(result))

    interactions = [value for value in interaction_maps.values() if value.get("matches")]
    interactions.sort(
        key=lambda item: item.get("start_message", {}).get("timestamp") or "", reverse=True
    )
    return interactions


def _group_results_by_session(
    search_index: SearchIndex, interactions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    session_map: dict[str, dict[str, Any]] = {}
    for interaction in interactions:
        session_id = str(interaction["session_id"])
        group = session_map.get(session_id)
        if group is None:
            session = search_index.get_session(session_id) or {"session_id": session_id}
            group = {
                "session_id": session_id,
                "project_directory": session.get("project_directory"),
                "session_path": session.get("session_path"),
                "created_at": session.get("created_at"),
                "last_message_at": session.get("last_message_at"),
                "interactions": [],
            }
            session_map[session_id] = group
        group["interactions"].append(interaction)

    session_groups = list(session_map.values())
    for group in session_groups:
        group["interactions"].sort(
            key=lambda item: item.get("start_message", {}).get("timestamp") or "",
            reverse=True,
        )
    session_groups.sort(key=lambda item: item.get("last_message_at") or "", reverse=True)
    return session_groups


def _build_interaction_index(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    interactions: list[dict[str, Any]] = []
    message_map: dict[str, str] = {}
    current: dict[str, object] | None = None
    pending: list[str] = []

    for message in messages:
        role = message.get("role")
        if current is None or role == "user":
            message_id = str(message["message_id"])
            current = {
                "interaction_id": message_id,
                "session_id": str(message["session_id"]),
                "start_message": message,
                "matches": [],
            }
            interactions.append(current)
            for pending_id in pending:
                message_map[pending_id] = str(current["interaction_id"])
            pending = []
        elif current is None:
            pending.append(str(message["message_id"]))
            continue
        message_map[str(message["message_id"])] = str(current["interaction_id"])

    return interactions, message_map


def _build_match_preview(result: dict[str, Any]) -> dict[str, Any]:
    match_source = result.get("match_source")
    preview: Any = ""
    if match_source == "tool":
        preview = (
            result.get("tool_result")
            or result.get("tool_input")
            or result.get("command")
            or result.get("file_path")
            or ""
        )
    else:
        preview = result.get("text_content") or ""
    preview = str(preview).replace("\n", " ").strip()
    if len(preview) > 180:
        preview = f"{preview[:180]}..."
    return {
        "message_id": result.get("message_id"),
        "match_source": match_source,
        "role": result.get("role"),
        "tool_name": result.get("tool_name"),
        "preview": preview,
        "timestamp": result.get("timestamp"),
    }


def run_server(search_index: SearchIndex, host: str, port: int, open_browser: bool) -> None:
    app = create_app(search_index)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
