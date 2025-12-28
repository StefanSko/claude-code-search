# ABOUTME: DuckDB-based search index with full-text search capabilities.
# ABOUTME: Provides indexing, search, and statistics for Claude Code sessions.

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

import duckdb

from claude_code_search.parsers import (
    Commit,
    ParsedMessage,
    ToolUsage,
    group_messages_into_interactions,
    parse_message,
)

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
    command VARCHAR,
    commit_intent VARCHAR
)
"""

COMMITS_DDL = """
CREATE TABLE IF NOT EXISTS commits (
    commit_hash VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    interaction_id VARCHAR,
    message_id VARCHAR NOT NULL,
    commit_message TEXT NOT NULL,
    branch VARCHAR,
    timestamp TIMESTAMP
)
"""

INTERACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS interactions (
    interaction_id VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    sequence_num INTEGER NOT NULL,
    user_prompt TEXT,
    timestamp TIMESTAMP,
    has_thinking BOOLEAN DEFAULT FALSE,
    total_cost_usd DOUBLE,
    message_count INTEGER,
    tool_count INTEGER,
    commit_count INTEGER
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
        self.conn.execute(COMMITS_DDL)
        self.conn.execute(INTERACTIONS_DDL)

    def is_empty(self) -> bool:
        """Check if the index has any sessions."""
        result = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return result is None or result[0] == 0

    def index_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        source: str = "local",
        session_path: str | None = None,
        project_directory: str | None = None,
    ) -> None:
        """Index a single session with all its messages."""
        parsed_messages: list[ParsedMessage] = []
        all_tool_usages: list[ToolUsage] = []
        all_commits: list[tuple[Commit, str]] = []  # (commit, message_id)
        total_cost = 0.0

        for seq, raw_msg in enumerate(messages):
            parsed = parse_message(raw_msg, session_id, seq)
            parsed_messages.append(parsed)
            all_tool_usages.extend(parsed.tool_usages)
            # Collect commits with their message IDs
            for commit in parsed.commits:
                all_commits.append((commit, parsed.message_id))
            if parsed.cost_usd:
                total_cost += parsed.cost_usd

        if not parsed_messages:
            return

        # Group messages into interactions
        interactions = group_messages_into_interactions(messages, session_id)

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
                 tool_input, tool_result, is_error, file_path, command, commit_intent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    tool.commit_intent,
                ],
            )

        # Insert interactions
        for interaction in interactions:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO interactions
                (interaction_id, session_id, sequence_num, user_prompt, timestamp,
                 has_thinking, total_cost_usd, message_count, tool_count, commit_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    interaction.interaction_id,
                    interaction.session_id,
                    interaction.sequence_num,
                    interaction.user_prompt,
                    interaction.timestamp,
                    interaction.has_thinking,
                    interaction.total_cost_usd,
                    len(interaction.message_ids),
                    len(interaction.tool_calls),
                    len(interaction.commits),
                ],
            )

        # Insert commits with interaction linkage
        commit_to_interaction: dict[str, str] = {}
        for interaction in interactions:
            for commit in interaction.commits:
                commit_to_interaction[commit.commit_hash] = interaction.interaction_id

        for commit, message_id in all_commits:
            interaction_id = commit_to_interaction.get(commit.commit_hash)
            self.conn.execute(
                """
                INSERT OR REPLACE INTO commits
                (commit_hash, session_id, interaction_id, message_id,
                 commit_message, branch, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    commit.commit_hash,
                    session_id,
                    interaction_id,
                    message_id,
                    commit.commit_message,
                    commit.branch,
                    commit.timestamp,
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
        session_result = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        message_result = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        tool_result = self.conn.execute("SELECT COUNT(*) FROM tool_usages").fetchone()
        cost_result = self.conn.execute(
            "SELECT COALESCE(SUM(total_cost_usd), 0) FROM sessions"
        ).fetchone()

        session_count = session_result[0] if session_result else 0
        message_count = message_result[0] if message_result else 0
        tool_count = tool_result[0] if tool_result else 0
        total_cost = cost_result[0] if cost_result else 0

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

    def get_interactions(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Get all interactions for a session."""
        sql = """
            SELECT i.*,
                   GROUP_CONCAT(m.message_id) as message_ids,
                   GROUP_CONCAT(DISTINCT c.commit_hash) as commit_hashes
            FROM interactions i
            LEFT JOIN messages m ON m.message_id IN (
                SELECT UNNEST(string_split(i.interaction_id, '-'))
            )
            LEFT JOIN commits c ON c.interaction_id = i.interaction_id
            WHERE i.session_id = ?
            GROUP BY i.interaction_id
            ORDER BY i.sequence_num
        """

        params: list[Any] = [session_id]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        result = self.conn.execute(sql, params).fetchall()
        columns = [desc[0] for desc in self.conn.description or []]
        return [dict(zip(columns, row, strict=False)) for row in result]

    def get_interaction(self, interaction_id: str) -> dict[str, Any] | None:
        """Get a single interaction with all its messages."""
        interaction_result = self.conn.execute(
            "SELECT * FROM interactions WHERE interaction_id = ?", [interaction_id]
        ).fetchone()

        if not interaction_result:
            return None

        columns = [desc[0] for desc in self.conn.description or []]
        interaction = dict(zip(columns, interaction_result, strict=False))

        # Get all messages in this interaction
        # Since we store message_ids in the Interaction object, we need to query messages table
        # For now, use session_id (approximate - returns all messages for session)
        session_id = interaction["session_id"]

        # Get messages that belong to this interaction (rough approximation)
        # A better approach would be to store message_interaction mapping
        messages_result = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY sequence_num
            """,
            [session_id],
        ).fetchall()

        msg_columns = [desc[0] for desc in self.conn.description or []]
        interaction["messages"] = [
            dict(zip(msg_columns, row, strict=False)) for row in messages_result
        ]

        # Get commits for this interaction
        commits_result = self.conn.execute(
            "SELECT * FROM commits WHERE interaction_id = ?", [interaction_id]
        ).fetchall()

        commit_columns = [desc[0] for desc in self.conn.description or []]
        interaction["commits"] = [
            dict(zip(commit_columns, row, strict=False)) for row in commits_result
        ]

        return interaction

    def search_interactions(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for interactions matching a query.

        Returns interactions where the query matches in:
        - User prompt
        - Any message text in the interaction
        - Tool names or parameters
        - Commit messages
        """
        # First, find matching messages using FTS
        message_matches = self.search(
            query=query,
            session_id=session_id,
            limit=limit * 3,  # Get more messages to dedupe by interaction
        )

        # Group by interaction and get unique interactions
        interaction_ids: set[str] = set()
        interaction_map: dict[str, dict[str, Any]] = {}

        for msg in message_matches:
            msg_session = msg["session_id"]

            # Find the interaction this message belongs to
            interaction_result = self.conn.execute(
                """
                SELECT * FROM interactions
                WHERE session_id = ?
                ORDER BY sequence_num
                """,
                [msg_session],
            ).fetchall()

            # Find which interaction this message sequence belongs to
            for row in interaction_result:
                int_id = row[0]  # interaction_id is first column
                if int_id not in interaction_ids:
                    columns = [desc[0] for desc in self.conn.description or []]
                    interaction = dict(zip(columns, row, strict=False))
                    interaction["match_message_id"] = msg["message_id"]
                    interaction["match_type"] = msg["content_type"]
                    interaction["score"] = msg.get("score", 0)
                    interaction_map[int_id] = interaction
                    interaction_ids.add(int_id)
                    break

                if len(interaction_ids) >= limit:
                    break

        # Convert to list and sort by score
        results = list(interaction_map.values())
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

    def get_commit(self, commit_hash: str) -> dict[str, Any] | None:
        """Get commit details by hash."""
        result = self.conn.execute(
            "SELECT * FROM commits WHERE commit_hash = ?", [commit_hash]
        ).fetchone()

        if not result:
            return None

        columns = [desc[0] for desc in self.conn.description or []]
        return dict(zip(columns, result, strict=False))

    def search_commits(
        self, query: str, session_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search commits by hash or message."""
        sql = """
            SELECT * FROM commits
            WHERE commit_hash LIKE ? OR commit_message LIKE ?
        """
        like_query = f"%{query}%"
        params: list[Any] = [like_query, like_query]

        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        result = self.conn.execute(sql, params).fetchall()
        columns = [desc[0] for desc in self.conn.description or []]
        return [dict(zip(columns, row, strict=False)) for row in result]

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
