from __future__ import annotations

import re
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
        message_results = self._search_messages(
            query=query,
            role=role,
            tool=tool,
            session_id=session_id,
            since=since,
            until=until,
            limit=limit,
        )
        tool_results = self._search_tools(
            query=query,
            role=role,
            tool=tool,
            session_id=session_id,
            since=since,
            until=until,
            limit=limit,
        )
        combined = message_results + tool_results
        if self.fts_enabled:
            combined.sort(key=lambda row: row.get("score", 0.0), reverse=True)
        else:
            combined.sort(key=lambda row: row.get("timestamp") or "", reverse=True)
        return combined[:limit]

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

    def get_interaction(self, session_id: str, interaction_id: str) -> dict[str, Any]:
        start_message = self.get_message(interaction_id)
        if start_message is None:
            raise KeyError(f"Message not found: {interaction_id}")
        if start_message["session_id"] != session_id:
            raise KeyError(f"Message {interaction_id} not in session {session_id}")

        start_sequence = start_message["sequence_num"]
        prev_user = self._fetchall(
            """
            SELECT sequence_num FROM messages
            WHERE session_id = ? AND role = 'user' AND sequence_num < ?
            ORDER BY sequence_num DESC
            LIMIT 1
            """,
            [session_id, start_sequence],
        )
        interaction_start = prev_user[0]["sequence_num"] + 1 if prev_user else 0
        next_user = self._fetchall(
            """
            SELECT sequence_num FROM messages
            WHERE session_id = ? AND role = 'user' AND sequence_num > ?
            ORDER BY sequence_num ASC
            LIMIT 1
            """,
            [session_id, start_sequence],
        )
        end_sequence = next_user[0]["sequence_num"] - 1 if next_user else None

        if end_sequence is None:
            message_rows = self._fetchall(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND sequence_num >= ?
                ORDER BY sequence_num ASC
                """,
                [session_id, interaction_start],
            )
            tool_rows = self._fetchall(
                """
                SELECT t.*, m.sequence_num FROM tool_usages t
                JOIN messages m ON m.message_id = t.message_id
                WHERE t.session_id = ? AND m.sequence_num >= ?
                ORDER BY m.sequence_num ASC, t.tool_usage_id ASC
                """,
                [session_id, interaction_start],
            )
        else:
            message_rows = self._fetchall(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND sequence_num BETWEEN ? AND ?
                ORDER BY sequence_num ASC
                """,
                [session_id, interaction_start, end_sequence],
            )
            tool_rows = self._fetchall(
                """
                SELECT t.*, m.sequence_num FROM tool_usages t
                JOIN messages m ON m.message_id = t.message_id
                WHERE t.session_id = ? AND m.sequence_num BETWEEN ? AND ?
                ORDER BY m.sequence_num ASC, t.tool_usage_id ASC
                """,
                [session_id, interaction_start, end_sequence],
            )

        tools_by_message: dict[str, list[dict[str, Any]]] = {}
        for tool in tool_rows:
            tools_by_message.setdefault(tool["message_id"], []).append(tool)

        messages = []
        commit_ids: set[str] = set()
        for message in message_rows:
            message_tools = tools_by_message.get(message["message_id"], [])
            message["tool_usages"] = message_tools
            commit_ids.update(_extract_commit_ids(message.get("text_content")))
            commit_ids.update(_extract_commit_ids(message.get("thinking_content")))
            for tool in message_tools:
                commit_ids.update(
                    _extract_commit_ids(
                        tool.get("tool_input"),
                        tool.get("tool_result"),
                        tool.get("command"),
                        tool.get("file_path"),
                    )
                )
            messages.append(message)

        return {
            "interaction_id": interaction_id,
            "session_id": session_id,
            "start_message": start_message,
            "messages": messages,
            "commit_ids": sorted(commit_ids),
        }

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT message_id, session_id, sequence_num, role, timestamp, text_content
            FROM messages WHERE session_id = ?
            ORDER BY sequence_num ASC
            """,
            [session_id],
        )

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
            "SELECT m.*, s.project_directory, s.session_path, "
            "'message' AS match_source, NULL AS tool_name, NULL AS tool_input, "
            "NULL AS tool_result, NULL AS command, NULL AS file_path "
            "FROM matches m "
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
            "SELECT m.*, s.project_directory, s.session_path, 0.0 as score, "
            "'message' AS match_source, NULL AS tool_name, NULL AS tool_input, "
            "NULL AS tool_result, NULL AS command, NULL AS file_path "
            "FROM messages m JOIN sessions s ON m.session_id = s.session_id "
            "WHERE m.searchable_text ILIKE ?"
        )
        params: list[Any] = [f"%{query}%"]
        sql, params = self._append_filters(sql, params, role, tool, session_id, since, until)
        sql += " ORDER BY m.timestamp DESC NULLS LAST LIMIT ?"
        params.append(limit)
        return sql, params

    def _search_messages(
        self,
        query: str,
        role: str | None,
        tool: str | None,
        session_id: str | None,
        since: str | None,
        until: str | None,
        limit: int,
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

    def _search_tools(
        self,
        query: str,
        role: str | None,
        tool: str | None,
        session_id: str | None,
        since: str | None,
        until: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.fts_enabled:
            sql = (
                "WITH matches AS ("
                "SELECT *, fts_main_tool_usages.match_bm25("
                "tool_usage_id, ?, fields := 'tool_input,tool_result,command,file_path'"
                ") AS score FROM tool_usages"
                ") "
                "SELECT m.message_id, m.session_id, m.sequence_num, m.timestamp, "
                "'tool' AS role, "
                "COALESCE(t.tool_result, t.tool_input, t.command, t.file_path) AS text_content, "
                "m.thinking_content, t.tool_usage_id, t.tool_name, t.tool_input, t.tool_result, "
                "t.command, t.file_path, s.project_directory, s.session_path, "
                "t.score AS score, 'tool' AS match_source "
                "FROM matches t "
                "JOIN messages m ON m.message_id = t.message_id "
                "JOIN sessions s ON m.session_id = s.session_id "
                "WHERE t.score IS NOT NULL"
            )
            params: list[Any] = [query]
        else:
            sql = (
                "SELECT m.message_id, m.session_id, m.sequence_num, m.timestamp, "
                "'tool' AS role, "
                "COALESCE(t.tool_result, t.tool_input, t.command, t.file_path) AS text_content, "
                "m.thinking_content, t.tool_usage_id, t.tool_name, t.tool_input, t.tool_result, "
                "t.command, t.file_path, s.project_directory, s.session_path, "
                "0.0 as score, 'tool' AS match_source "
                "FROM tool_usages t "
                "JOIN messages m ON m.message_id = t.message_id "
                "JOIN sessions s ON m.session_id = s.session_id "
                "WHERE (t.tool_input ILIKE ? OR t.tool_result ILIKE ? "
                "OR t.command ILIKE ? OR t.file_path ILIKE ?)"
            )
            params = [f"%{query}%"] * 4

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
            sql += " AND t.tool_name = ?"
            params.append(tool)
        sql += " ORDER BY score DESC LIMIT ?"
        params.append(limit)
        return self._fetchall(sql, params)

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


def _extract_commit_ids(*values: Any) -> set[str]:
    commits: set[str] = set()
    pattern = re.compile(r"\b[0-9a-f]{7,40}\b")
    for value in values:
        if not value:
            continue
        text = str(value)
        for match in pattern.findall(text):
            commits.add(match)
    return commits
