from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import questionary
from click_default_group import DefaultGroup

from .formatters import format_results, render_results, render_results_table
from .index import SearchIndex
from .loaders import discover_sessions, load_session, resolve_session_metadata
from .server.app import run_server


@click.group(cls=DefaultGroup, default="serve", default_if_no_args=True)
def cli() -> None:
    """Search Claude Code transcripts via CLI or web UI."""


@cli.command()
@click.option("--db", default=":memory:", help="Database path")
@click.option("--port", default=8765, show_default=True, help="Port to serve on")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
@click.option("--reindex", is_flag=True, help="Re-select and index sessions")
@click.option(
    "--source",
    type=click.Choice(["local", "web", "all"], case_sensitive=False),
    default="all",
    show_default=True,
)
@click.option(
    "--sessions-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Local sessions directory override",
)
def serve(
    db: str,
    port: int,
    host: str,
    no_open: bool,
    reindex: bool,
    source: str,
    sessions_dir: Path | None,
) -> None:
    """Launch the web UI for searching sessions."""
    index = SearchIndex(db)
    needs_indexing = db == ":memory:" or reindex or index.is_empty()

    if needs_indexing:
        selected_sessions = _select_sessions(source=source, sessions_dir=sessions_dir)
        if not selected_sessions:
            click.echo(
                "No sessions selected. Use --sessions-dir or set "
                "CLAUDE_CODE_SESSIONS_DIR if none appear."
            )
            return
        _index_selected_sessions(index, selected_sessions, sessions_dir=sessions_dir)

    click.echo(f"\nStarting server at http://{host}:{port}")
    run_server(index, host, port, open_browser=not no_open)


@cli.command()
@click.option("--db", default=":memory:", help="Database path")
@click.option(
    "--source",
    type=click.Choice(["local", "web", "all"], case_sensitive=False),
    default="all",
    show_default=True,
)
@click.option("--session", "sessions", multiple=True, help="Session ID to index")
@click.option("--all-local", is_flag=True, help="Index all local sessions")
@click.option("--all-web", is_flag=True, help="Index all web sessions")
@click.option("--append", is_flag=True, help="Append to existing index")
@click.option("--since", default=None, help="Only sessions after date")
@click.option("--project", default=None, help="Filter by project directory")
@click.option(
    "--sessions-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Local sessions directory override",
)
def index(
    db: str,
    source: str,
    sessions: tuple[str, ...],
    all_local: bool,
    all_web: bool,
    append: bool,
    since: str | None,
    project: str | None,
    sessions_dir: Path | None,
) -> None:
    """Index sessions into DuckDB."""
    if all_local and all_web:
        source = "all"
    elif all_local:
        source = "local"
    elif all_web:
        source = "web"

    indexer = SearchIndex(db)
    if not append:
        indexer.clear()

    if sessions:
        selected_sessions = []
        for session_id in sessions:
            metadata = resolve_session_metadata(session_id, source=source, root_dir=sessions_dir)
            selected_sessions.append(metadata or {"id": session_id, "source": source})
    elif all_local or all_web:
        selected_sessions = discover_sessions(source=source, root_dir=sessions_dir)
    else:
        selected_sessions = _select_sessions(
            source=source, since=since, project=project, sessions_dir=sessions_dir
        )

    if not selected_sessions:
        click.echo(
            "No sessions selected. Use --sessions-dir or set "
            "CLAUDE_CODE_SESSIONS_DIR if none appear."
        )
        return

    _index_selected_sessions(indexer, selected_sessions, sessions_dir=sessions_dir)
    stats = indexer.get_stats()
    click.echo(
        f"\nIndex created: {stats['message_count']} messages, {stats['tool_count']} tool calls"
    )


@cli.command()
@click.argument("query")
@click.option("--db", default=":memory:", help="Database path")
@click.option("--role", type=click.Choice(["user", "assistant"], case_sensitive=False))
@click.option("--tool", default=None, help="Filter by tool name")
@click.option("--session", "session_id", default=None, help="Filter by session ID")
@click.option("--since", default=None, help="Messages after date")
@click.option("--until", default=None, help="Messages before date")
@click.option("--limit", default=20, show_default=True, help="Max results")
@click.option("--context", default=0, show_default=True, help="Include N surrounding messages")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["rich", "table", "json", "csv"], case_sensitive=False),
    default="rich",
    show_default=True,
)
def search(
    query: str,
    db: str,
    role: str | None,
    tool: str | None,
    session_id: str | None,
    since: str | None,
    until: str | None,
    limit: int,
    context: int,
    output_format: str,
) -> None:
    """Search indexed sessions."""
    indexer = SearchIndex(db)
    results = indexer.search(
        query=query,
        role=role,
        tool=tool,
        session_id=session_id,
        since=since,
        until=until,
        limit=limit,
    )

    if context > 0:
        enriched: list[dict[str, Any]] = []
        for result in results:
            ctx = indexer.get_message_with_context(
                result["message_id"], before=context, after=context
            )
            enriched.append(ctx)
        results_to_output: Any = enriched
    else:
        results_to_output = results

    formatted = format_results(results_to_output, output_format)
    if formatted is not None:
        click.echo(formatted)
        return

    if output_format == "table":
        render_results_table(results)
    else:
        render_results(results)


@cli.command(name="list")
@click.option("--db", default=":memory:", help="Database path")
def list_sessions(db: str) -> None:
    """List indexed sessions."""
    indexer = SearchIndex(db)
    sessions = indexer.list_sessions()
    for session in sessions:
        click.echo(f"{session['session_id']}\t{session.get('message_count', 0)} messages")


@cli.command()
@click.option("--db", default=":memory:", help="Database path")
def stats(db: str) -> None:
    """Show index statistics."""
    indexer = SearchIndex(db)
    data = indexer.get_stats()
    click.echo(f"Sessions indexed: {data['session_count']}")
    click.echo(f"Total messages: {data['message_count']}")
    click.echo(f"Tool usages: {data['tool_count']}")
    click.echo(f"Date range: {data['date_range']['start']} to {data['date_range']['end']}")
    click.echo(f"Total cost: ${data['total_cost_usd']:.2f}")


@cli.command()
@click.argument("query")
@click.option("--db", default=":memory:", help="Database path")
@click.option("--format", type=click.Choice(["json", "csv"], case_sensitive=False), default="json")
@click.option("--role", type=click.Choice(["user", "assistant"], case_sensitive=False))
@click.option("--tool", default=None, help="Filter by tool name")
@click.option("--session", "session_id", default=None, help="Filter by session ID")
@click.option("--since", default=None, help="Messages after date")
@click.option("--until", default=None, help="Messages before date")
def export(
    query: str,
    db: str,
    format: str,
    role: str | None,
    tool: str | None,
    session_id: str | None,
    since: str | None,
    until: str | None,
) -> None:
    """Export search results as JSON or CSV."""
    indexer = SearchIndex(db)
    results = indexer.search(
        query=query,
        role=role,
        tool=tool,
        session_id=session_id,
        since=since,
        until=until,
        limit=1000,
    )
    formatted = format_results(results, format)
    click.echo(formatted or "")


def _select_sessions(
    source: str,
    since: str | None = None,
    project: str | None = None,
    sessions_dir: Path | None = None,
) -> list[dict[str, Any]]:
    sessions = discover_sessions(source=source, root_dir=sessions_dir)
    sessions = _filter_sessions(sessions, since=since, project=project)
    if not sessions:
        click.echo(
            "No sessions discovered. Use --sessions-dir or set "
            "CLAUDE_CODE_SESSIONS_DIR if your sessions live elsewhere."
        )
        return []

    choices = [
        questionary.Choice(
            title=_format_session_choice(session),
            value=session,
            checked=True,
        )
        for session in sessions[:50]
    ]
    selected = questionary.checkbox(
        "Select sessions to index (Space to toggle, Enter to confirm):",
        choices=choices,
    ).ask()
    return selected or []


def _format_session_choice(session: dict[str, Any]) -> str:
    preview = session.get("preview") or ""
    preview = preview.replace("\n", " ")
    preview = preview[:60] + ("..." if len(preview) > 60 else "")
    modified = session.get("modified")
    age = _format_age(modified)
    count = session.get("message_count") or "?"
    session_id = session.get("id", "")
    return f'{session_id[:8]}  {age}  "{preview}"  {count} msgs'


def _format_age(modified: Any) -> str:
    if not isinstance(modified, (int, float)):
        return "unknown"
    now = datetime.now(tz=timezone.utc).timestamp()
    delta = max(now - modified, 0)
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _filter_sessions(
    sessions: list[dict[str, Any]],
    since: str | None,
    project: str | None,
) -> list[dict[str, Any]]:
    filtered = sessions
    if since:
        filtered = [session for session in filtered if _is_after(session, since)]
    if project:
        filtered_sessions: list[dict[str, Any]] = []
        for session in filtered:
            project_directory = session.get("project_directory")
            if isinstance(project_directory, str) and project_directory.startswith(project):
                filtered_sessions.append(session)
        filtered = filtered_sessions
    return filtered


def _is_after(session: dict[str, Any], since: str) -> bool:
    try:
        since_dt = datetime.fromisoformat(since)
    except ValueError:
        return True

    created_at = session.get("created_at")
    if isinstance(created_at, str):
        try:
            session_dt = datetime.fromisoformat(created_at)
            return session_dt >= since_dt
        except ValueError:
            return True

    modified = session.get("modified")
    if isinstance(modified, (int, float)):
        session_dt = datetime.fromtimestamp(modified, tz=timezone.utc)
        return session_dt >= since_dt
    return True


def _index_selected_sessions(
    indexer: SearchIndex,
    sessions: list[dict[str, Any]],
    sessions_dir: Path | None,
) -> None:
    click.echo(f"Indexing {len(sessions)} sessions...")
    for session in sessions:
        session_id = session.get("id")
        if not isinstance(session_id, str):
            continue
        source = session.get("source") or "local"
        messages = load_session(
            session_id,
            source=source,
            root_dir=sessions_dir,
            session_path=session.get("path"),
        )
        indexer.index_session(
            session_id=session_id,
            messages=messages,
            source=source,
            session_path=session.get("path"),
            project_directory=session.get("project_directory"),
        )
        click.echo(f"  OK {session_id[:8]}")
