# ABOUTME: DuckDB-based search index with full-text search capabilities.
# ABOUTME: Provides indexing, search, and statistics for Claude Code sessions.

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

import duckdb

from claude_code_search.parsers import ParsedMessage, ToolUsage, parse_message

SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    session_path VARCHAR,
    project_directory VARCHAR,
    created_at TIMESTAMP,
    last_message_at TIMESTAMP,
    message_count INTEGER,
    total_cost_usd DOUBLE,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    message_id VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    sequence_num INTEGER NOT NULL,
    role VARCHAR NOT NULL,
    timestamp TIMESTAMP,
    text_content TEXT,
    thinking_content TEXT,
    cost_usd DOUBLE,
    duration_ms INTEGER,
    searchable_text TEXT,
    content_type VARCHAR,
    tool_summary TEXT
)
"""

TOOL_USAGES_DDL = """
CREATE TABLE IF NOT EXISTS tool_usages (
    tool_usage_id VARCHAR PRIMARY KEY,
    message_id VARCHAR NOT NULL,
    session_id VARCHAR NOT NULL,
    tool_name VARCHAR NOT NULL,
    tool_input TEXT,
    tool_result TEXT,
    is_error BOOLEAN DEFAULT FALSE,
    file_path VARCHAR,
    command VARCHAR
)
"""


class SearchIndex:
    """DuckDB-based search index for Claude Code sessions."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema and FTS extension."""
        self.conn.execute("INSTALL fts; LOAD fts;")
        self.conn.execute(SESSIONS_DDL)
        self.conn.execute(MESSAGES_DDL)
        self.conn.execute(TOOL_USAGES_DDL)

    def is_empty(self) -> bool:
        """Check if the index has any sessions."""
        result = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return result is None or result[0] == 0

    def index_session(
        self,
        session_id: str,
        messages: list[dict],
        source: str = "local",
        session_path: str | None = None,
        project_directory: str | None = None,
    ) -> None:
        """Index a single session with all its messages."""
        parsed_messages: list[ParsedMessage] = []
        all_tool_usages: list[ToolUsage] = []
        total_cost = 0.0

        for seq, raw_msg in enumerate(messages):
            parsed = parse_message(raw_msg, session_id, seq)
            parsed_messages.append(parsed)
            all_tool_usages.extend(parsed.tool_usages)
            if parsed.cost_usd:
                total_cost += parsed.cost_usd

        if not parsed_messages:
            return

        first_ts = parsed_messages[0].timestamp
        last_ts = parsed_messages[-1].timestamp

        self.conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (session_id, source, session_path, project_directory,
             created_at, last_message_at, message_count, total_cost_usd, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                session_id,
                source,
                session_path,
                project_directory,
                first_ts,
                last_ts,
                len(parsed_messages),
                total_cost,
                datetime.now(UTC).isoformat(),
            ],
        )

        for msg in parsed_messages:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (message_id, session_id, sequence_num, role, timestamp,
                 text_content, thinking_content, cost_usd, duration_ms, searchable_text,
                 content_type, tool_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    msg.message_id,
                    msg.session_id,
                    msg.sequence_num,
                    msg.role,
                    msg.timestamp,
                    msg.text_content,
                    msg.thinking_content,
                    msg.cost_usd,
                    msg.duration_ms,
                    msg.searchable_text,
                    msg.content_type,
                    msg.tool_summary,
                ],
            )

        for tool in all_tool_usages:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO tool_usages
                (tool_usage_id, message_id, session_id, tool_name,
                 tool_input, tool_result, is_error, file_path, command)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    tool.tool_usage_id,
                    tool.message_id,
                    tool.session_id,
                    tool.tool_name,
                    tool.tool_input,
                    tool.tool_result,
                    tool.is_error,
                    tool.file_path,
                    tool.command,
                ],
            )

        self._rebuild_fts()

    def _rebuild_fts(self) -> None:
        """Rebuild full-text search indexes."""
        with contextlib.suppress(duckdb.CatalogException):
            self.conn.execute("DROP INDEX IF EXISTS fts_main_messages")

        with contextlib.suppress(duckdb.CatalogException):
            self.conn.execute(
                """
                PRAGMA create_fts_index(
                    'messages', 'message_id',
                    'searchable_text',
                    stemmer='english',
                    stopwords='english',
                    overwrite=1
                )
                """
            )

    def search(
        self,
        query: str,
        role: str | None = None,
        tool: str | None = None,
        session_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        content_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Execute a full-text search query with optional filters."""
        sql = """
            WITH matches AS (
                SELECT *, fts_main_messages.match_bm25(
                    message_id, ?, fields := 'searchable_text'
                ) AS score
                FROM messages
                WHERE score IS NOT NULL
            )
            SELECT m.*, s.project_directory, s.source
            FROM matches m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE 1=1
        """
        params: list[Any] = [query]

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

        if content_type:
            if content_type == "tool":
                # "tool" matches both tool_use and tool_result
                sql += " AND m.content_type IN ('tool_use', 'tool_result')"
            else:
                sql += " AND m.content_type = ?"
                params.append(content_type)

        sql += " ORDER BY score DESC LIMIT ?"
        params.append(limit)

        result = self.conn.execute(sql, params).fetchall()
        columns = [desc[0] for desc in self.conn.description or []]
        return [dict(zip(columns, row, strict=False)) for row in result]

    def search_tools(
        self, query: str, tool_name: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search within tool usages."""
        sql = """
            SELECT * FROM tool_usages
            WHERE tool_input LIKE ? OR tool_result LIKE ? OR command LIKE ?
        """
        like_query = f"%{query}%"
        params: list[Any] = [like_query, like_query, like_query]

        if tool_name:
            sql += " AND tool_name = ?"
            params.append(tool_name)

        sql += " LIMIT ?"
        params.append(limit)

        result = self.conn.execute(sql, params).fetchall()
        columns = [desc[0] for desc in self.conn.description or []]
        return [dict(zip(columns, row, strict=False)) for row in result]

    def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        session_count = self.conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        message_count = self.conn.execute(
            "SELECT COUNT(*) FROM messages"
        ).fetchone()[0]
        tool_count = self.conn.execute(
            "SELECT COUNT(*) FROM tool_usages"
        ).fetchone()[0]
        total_cost = self.conn.execute(
            "SELECT COALESCE(SUM(total_cost_usd), 0) FROM sessions"
        ).fetchone()[0]

        date_range = self.conn.execute(
            """
            SELECT MIN(timestamp), MAX(timestamp)
            FROM messages
            WHERE timestamp IS NOT NULL
            """
        ).fetchone()

        return {
            "session_count": session_count,
            "message_count": message_count,
            "tool_count": tool_count,
            "total_cost_usd": round(total_cost, 4) if total_cost else 0,
            "earliest_message": date_range[0] if date_range else None,
            "latest_message": date_range[1] if date_range else None,
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all indexed sessions."""
        result = self.conn.execute(
            """
            SELECT session_id, source, project_directory,
                   created_at, last_message_at, message_count, total_cost_usd
            FROM sessions
            ORDER BY last_message_at DESC
            """
        ).fetchall()
        columns = [desc[0] for desc in self.conn.description or []]
        return [dict(zip(columns, row, strict=False)) for row in result]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get a single session with all its messages."""
        session_result = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", [session_id]
        ).fetchone()

        if not session_result:
            return None

        columns = [desc[0] for desc in self.conn.description or []]
        session = dict(zip(columns, session_result, strict=False))

        messages_result = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY sequence_num
            """,
            [session_id],
        ).fetchall()
        msg_columns = [desc[0] for desc in self.conn.description or []]
        session["messages"] = [dict(zip(msg_columns, row, strict=False)) for row in messages_result]

        return session

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Get a single message with its tool usages."""
        msg_result = self.conn.execute(
            "SELECT * FROM messages WHERE message_id = ?", [message_id]
        ).fetchone()

        if not msg_result:
            return None

        columns = [desc[0] for desc in self.conn.description or []]
        message = dict(zip(columns, msg_result, strict=False))

        tools_result = self.conn.execute(
            "SELECT * FROM tool_usages WHERE message_id = ?", [message_id]
        ).fetchall()
        tool_columns = [desc[0] for desc in self.conn.description or []]
        message["tool_usages"] = [
            dict(zip(tool_columns, row, strict=False)) for row in tools_result
        ]

        return message

    def get_message_with_context(
        self, message_id: str, before: int = 2, after: int = 2
    ) -> dict[str, Any] | None:
        """Get a message with surrounding context messages."""
        msg = self.get_message(message_id)
        if not msg:
            return None

        session_id = msg["session_id"]
        seq_num = msg["sequence_num"]

        context_result = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
              AND sequence_num >= ?
              AND sequence_num <= ?
            ORDER BY sequence_num
            """,
            [session_id, seq_num - before, seq_num + after],
        ).fetchall()

        columns = [desc[0] for desc in self.conn.description or []]
        context_messages = [dict(zip(columns, row, strict=False)) for row in context_result]

        return {
            "message": msg,
            "context": context_messages,
        }

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
