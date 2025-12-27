from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import duckdb

from .parsers import parse_message


class SearchIndex:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self.fts_enabled = True
        self._init_schema()

    def _init_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        self.conn.execute(schema_path.read_text())
        self._init_fts()

    def _init_fts(self) -> None:
        try:
            self.conn.execute("INSTALL fts;")
            self.conn.execute("LOAD fts;")
        except duckdb.Error:
            self.fts_enabled = False

    def is_empty(self) -> bool:
        row = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return row is not None and row[0] == 0

    def clear(self) -> None:
        self.conn.execute("DELETE FROM tool_usages")
        self.conn.execute("DELETE FROM messages")
        self.conn.execute("DELETE FROM sessions")

    def index_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        source: str,
        session_path: str | None = None,
        project_directory: str | None = None,
        replace_existing: bool = True,
    ) -> None:
        if replace_existing:
            self._delete_session(session_id)

        parsed_messages: list[dict[str, Any]] = []
        tool_rows: list[dict[str, Any]] = []
        total_cost = 0.0

        for seq, raw in enumerate(messages):
            message, tool_usages = parse_message(raw, session_id, seq)
            parsed_messages.append(message)
            cost = message.get("cost_usd")
            if cost:
                total_cost += float(cost)

            for idx, tool in enumerate(tool_usages):
                if not tool.get("tool_usage_id"):
                    tool["tool_usage_id"] = f"{message['message_id']}-tool-{idx}"
                tool_rows.append(tool)

        created_at = parsed_messages[0]["timestamp"] if parsed_messages else None
        last_message_at = parsed_messages[-1]["timestamp"] if parsed_messages else None

        self.conn.execute(
            """
            INSERT INTO sessions (
                session_id, source, session_path, project_directory,
                created_at, last_message_at, message_count, total_cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                session_id,
                source,
                session_path,
                project_directory,
                created_at,
                last_message_at,
                len(parsed_messages),
                total_cost,
            ],
        )

        if parsed_messages:
            self.conn.executemany(
                """
                INSERT INTO messages (
                    message_id, session_id, sequence_num, role, timestamp,
                    text_content, thinking_content, cost_usd, duration_ms, searchable_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        msg["message_id"],
                        msg["session_id"],
                        msg["sequence_num"],
                        msg["role"],
                        msg["timestamp"],
                        msg.get("text_content"),
                        msg.get("thinking_content"),
                        msg.get("cost_usd"),
                        msg.get("duration_ms"),
                        msg.get("searchable_text"),
                    )
                    for msg in parsed_messages
                ],
            )

        if tool_rows:
            self.conn.executemany(
                """
                INSERT INTO tool_usages (
                    tool_usage_id, message_id, session_id, tool_name, tool_input,
                    tool_result, is_error, file_path, command
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        tool["tool_usage_id"],
                        tool["message_id"],
                        tool["session_id"],
                        tool["tool_name"],
                        tool.get("tool_input"),
                        tool.get("tool_result"),
                        tool.get("is_error", False),
                        tool.get("file_path"),
                        tool.get("command"),
                    )
                    for tool in tool_rows
                ],
            )

        self._rebuild_fts()

    def _delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM tool_usages WHERE session_id = ?", [session_id])
        self.conn.execute("DELETE FROM messages WHERE session_id = ?", [session_id])
        self.conn.execute("DELETE FROM sessions WHERE session_id = ?", [session_id])

    def _rebuild_fts(self) -> None:
        if not self.fts_enabled:
            return
        self.conn.execute(
            """
            PRAGMA create_fts_index(
                'messages',
                'message_id',
                'searchable_text',
                stemmer='english',
                stopwords='english',
                overwrite=1
            );
            """
        )
        self.conn.execute(
            """
            PRAGMA create_fts_index(
                'tool_usages',
                'tool_usage_id',
                'tool_input', 'tool_result', 'command', 'file_path',
                stemmer='english',
                stopwords='english',
                overwrite=1
            );
            """
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM sessions ORDER BY last_message_at DESC NULLS LAST")

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        rows = self._fetchall("SELECT * FROM sessions WHERE session_id = ?", [session_id])
        return rows[0] if rows else None

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        rows = self._fetchall("SELECT * FROM messages WHERE message_id = ?", [message_id])
        return rows[0] if rows else None

    def get_message_with_context(
        self, message_id: str, before: int = 2, after: int = 2
    ) -> dict[str, Any]:
        message = self.get_message(message_id)
        if message is None:
            raise KeyError(f"Message not found: {message_id}")

        session_id = message["session_id"]
        sequence_num = message["sequence_num"]

        before_rows = self._fetchall(
            """
            SELECT * FROM messages
            WHERE session_id = ? AND sequence_num < ?
            ORDER BY sequence_num DESC
            LIMIT ?
            """,
            [session_id, sequence_num, before],
        )
        after_rows = self._fetchall(
            """
            SELECT * FROM messages
            WHERE session_id = ? AND sequence_num > ?
            ORDER BY sequence_num ASC
            LIMIT ?
            """,
            [session_id, sequence_num, after],
        )

        before_rows.reverse()
        return {"message": message, "before": before_rows, "after": after_rows}

    def get_stats(self) -> dict[str, Any]:
        session_row = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        message_row = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        tool_row = self.conn.execute("SELECT COUNT(*) FROM tool_usages").fetchone()
        range_row = self.conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM messages"
        ).fetchone()
        cost_row = self.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM messages").fetchone()

        session_count = int(session_row[0]) if session_row else 0
        message_count = int(message_row[0]) if message_row else 0
        tool_count = int(tool_row[0]) if tool_row else 0
        total_cost = float(cost_row[0]) if cost_row else 0.0
        range_start = range_row[0] if range_row else None
        range_end = range_row[1] if range_row else None

        return {
            "session_count": session_count,
            "message_count": message_count,
            "tool_count": tool_count,
            "date_range": {
                "start": range_start,
                "end": range_end,
            },
            "total_cost_usd": total_cost,
        }

    def search(
        self,
        query: str,
        role: str | None = None,
        tool: str | None = None,
        session_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if self.fts_enabled:
            sql, params = self._build_fts_query(
                query=query,
                role=role,
                tool=tool,
                session_id=session_id,
                since=since,
                until=until,
                limit=limit,
            )
            return self._fetchall(sql, params)

        sql, params = self._build_like_query(
            query=query,
            role=role,
            tool=tool,
            session_id=session_id,
            since=since,
            until=until,
            limit=limit,
        )
        return self._fetchall(sql, params)

    def search_tools(self, query: str, tool_name: str | None = None) -> list[dict[str, Any]]:
        if not self.fts_enabled:
            sql = "SELECT * FROM tool_usages WHERE tool_input ILIKE ?"
            params = [f"%{query}%"]
            if tool_name:
                sql += " AND tool_name = ?"
                params.append(tool_name)
            sql += " ORDER BY tool_usage_id LIMIT 20"
            return self._fetchall(sql, params)

        sql = (
            "SELECT *, fts_main_tool_usages.match_bm25("
            "tool_usage_id, ?, fields := 'tool_input,tool_result,command'"
            ") AS score FROM tool_usages WHERE score IS NOT NULL"
        )
        params: list[Any] = [query]
        if tool_name:
            sql += " AND tool_name = ?"
            params.append(tool_name)
        sql += " ORDER BY score DESC LIMIT 20"
        return self._fetchall(sql, params)

    def _build_fts_query(
        self,
        query: str,
        role: str | None,
        tool: str | None,
        session_id: str | None,
        since: str | None,
        until: str | None,
        limit: int,
    ) -> tuple[str, list[Any]]:
        sql = (
            "WITH matches AS ("
            "SELECT *, fts_main_messages.match_bm25("
            "message_id, ?, fields := 'searchable_text'"
            ") AS score FROM messages"
            ") "
            "SELECT m.*, s.project_directory, s.session_path FROM matches m "
            "JOIN sessions s ON m.session_id = s.session_id "
            "WHERE m.score IS NOT NULL"
        )
        params: list[Any] = [query]
        sql, params = self._append_filters(sql, params, role, tool, session_id, since, until)
        sql += " ORDER BY m.score DESC LIMIT ?"
        params.append(limit)
        return sql, params

    def _build_like_query(
        self,
        query: str,
        role: str | None,
        tool: str | None,
        session_id: str | None,
        since: str | None,
        until: str | None,
        limit: int,
    ) -> tuple[str, list[Any]]:
        sql = (
            "SELECT m.*, s.project_directory, s.session_path, 0.0 as score "
            "FROM messages m JOIN sessions s ON m.session_id = s.session_id "
            "WHERE m.searchable_text ILIKE ?"
        )
        params: list[Any] = [f"%{query}%"]
        sql, params = self._append_filters(sql, params, role, tool, session_id, since, until)
        sql += " ORDER BY m.timestamp DESC NULLS LAST LIMIT ?"
        params.append(limit)
        return sql, params

    def _append_filters(
        self,
        sql: str,
        params: list[Any],
        role: str | None,
        tool: str | None,
        session_id: str | None,
        since: str | None,
        until: str | None,
    ) -> tuple[str, list[Any]]:
        if role:
            sql += " AND m.role = ?"
            params.append(role)
        if session_id:
            sql += " AND m.session_id = ?"
            params.append(session_id)
        if since:
            sql += " AND m.timestamp >= ?"
            params.append(since)
        if until:
            sql += " AND m.timestamp <= ?"
            params.append(until)
        if tool:
            sql += (
                " AND EXISTS (SELECT 1 FROM tool_usages t "
                "WHERE t.message_id = m.message_id AND t.tool_name = ?)"
            )
            params.append(tool)
        return sql, params

    def _fetchall(self, sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
        cursor = self.conn.execute(sql, params or [])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
