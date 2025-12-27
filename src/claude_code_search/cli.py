# ABOUTME: Click-based CLI interface for Claude Code Search.
# ABOUTME: Provides commands for indexing, searching, and serving the web UI.

from __future__ import annotations

import click
import questionary
from click_default_group import DefaultGroup
from rich.console import Console

from claude_code_search.formatters import display_results, display_sessions, display_stats
from claude_code_search.index import SearchIndex
from claude_code_search.loaders import LocalSessionLoader
from claude_code_search.server import run_server

console = Console()


@click.group(cls=DefaultGroup, default="serve", default_if_no_args=True)
@click.version_option()
def cli() -> None:
    """Claude Code Search - Search across your Claude Code sessions."""
    pass


@cli.command()
@click.option("--db", default=":memory:", help="Database file path")
@click.option("--port", default=8765, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
@click.option("--reindex", is_flag=True, help="Re-select and index sessions")
@click.option(
    "--source",
    type=click.Choice(["local", "web", "all"]),
    default="local",
    help="Session source",
)
def serve(
    db: str,
    port: int,
    host: str,
    no_open: bool,
    reindex: bool,
    source: str,
) -> None:
    """Launch the web UI for searching sessions."""
    index = SearchIndex(db)

    needs_indexing = db == ":memory:" or reindex or index.is_empty()

    if needs_indexing:
        loader = LocalSessionLoader()
        sessions = loader.discover_sessions()

        if not sessions:
            console.print("[yellow]No sessions found.[/]")
            return

        choices = [
            questionary.Choice(
                title=(
                    f"{s.session_id[:12]}  {s.project_directory or '-':20}  "
                    f"{s.message_count:4} msgs  {s.preview[:40]}..."
                ),
                value=s.session_id,
                checked=True,
            )
            for s in sessions[:50]
        ]

        selected = questionary.checkbox(
            "Select sessions to index (Space to toggle, Enter to confirm):",
            choices=choices,
        ).ask()

        if not selected:
            console.print("[yellow]No sessions selected. Exiting.[/]")
            return

        console.print(f"\n[cyan]Indexing {len(selected)} sessions...[/]")

        for session_id in selected:
            messages = loader.load_session(session_id)
            session_info = next((s for s in sessions if s.session_id == session_id), None)
            index.index_session(
                session_id,
                messages,
                source="local",
                session_path=str(session_info.path) if session_info and session_info.path else None,
                project_directory=session_info.project_directory if session_info else None,
            )
            console.print(f"  [green]✓[/] {session_id[:12]} ({len(messages)} messages)")

        stats = index.get_stats()
        console.print(
            f"\n[green]Index created:[/] {stats['message_count']} messages, "
            f"{stats['tool_count']} tool calls"
        )

    console.print(f"\n[cyan]Starting server at http://{host}:{port}[/]")
    run_server(index, host, port, open_browser=not no_open)


@cli.command()
@click.option("--db", default=":memory:", help="Database file path")
@click.option("--source", type=click.Choice(["local", "web", "all"]), default="local")
@click.option("--session", "session_ids", multiple=True, help="Specific session IDs")
@click.option("--all-local", is_flag=True, help="Index all local sessions")
@click.option("--append", is_flag=True, help="Add to existing index")
def index(
    db: str,
    source: str,
    session_ids: tuple[str, ...],
    all_local: bool,
    append: bool,
) -> None:
    """Build or update the search index."""
    search_index = SearchIndex(db)
    loader = LocalSessionLoader()
    sessions = loader.discover_sessions()

    if not sessions:
        console.print("[yellow]No sessions found.[/]")
        return

    if session_ids:
        selected = list(session_ids)
    elif all_local:
        selected = [s.session_id for s in sessions]
    else:
        choices = [
            questionary.Choice(
                title=(
                    f"{s.session_id[:12]}  {s.project_directory or '-':20}  "
                    f"{s.message_count:4} msgs"
                ),
                value=s.session_id,
                checked=True,
            )
            for s in sessions[:50]
        ]
        selected = questionary.checkbox(
            "Select sessions to index:",
            choices=choices,
        ).ask()

    if not selected:
        console.print("[yellow]No sessions selected.[/]")
        return

    console.print(f"\n[cyan]Indexing {len(selected)} sessions...[/]")

    for session_id in selected:
        messages = loader.load_session(session_id)
        session_info = next((s for s in sessions if s.session_id == session_id), None)
        search_index.index_session(
            session_id,
            messages,
            source="local",
            session_path=str(session_info.path) if session_info and session_info.path else None,
            project_directory=session_info.project_directory if session_info else None,
        )
        console.print(f"  [green]✓[/] {session_id[:12]}")

    stats = search_index.get_stats()
    console.print(
        f"\n[green]Index complete:[/] {stats['message_count']} messages, "
        f"{stats['tool_count']} tool calls"
    )


@cli.command()
@click.argument("query")
@click.option("--db", default=":memory:", help="Database file path")
@click.option("--role", type=click.Choice(["user", "assistant"]), help="Filter by role")
@click.option("--tool", help="Filter by tool name")
@click.option("--session", help="Limit to session ID")
@click.option("--since", help="Messages after date")
@click.option("--until", help="Messages before date")
@click.option("--limit", default=20, help="Max results")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["rich", "table", "json"]),
    default="rich",
)
def search(
    query: str,
    db: str,
    role: str | None,
    tool: str | None,
    session: str | None,
    since: str | None,
    until: str | None,
    limit: int,
    format_type: str,
) -> None:
    """Search indexed sessions."""
    search_index = SearchIndex(db)

    if search_index.is_empty():
        console.print("[yellow]No sessions indexed. Run 'index' first.[/]")
        return

    results = search_index.search(
        query=query,
        role=role,
        tool=tool,
        session_id=session,
        since=since,
        until=until,
        limit=limit,
    )

    if not results:
        console.print(f"[yellow]No results found for '{query}'[/]")
        return

    display_results(results, format_type, console)


@cli.command("list")
@click.option("--db", default=":memory:", help="Database file path")
def list_sessions(db: str) -> None:
    """List indexed sessions."""
    search_index = SearchIndex(db)
    sessions = search_index.list_sessions()

    if not sessions:
        console.print("[yellow]No sessions indexed.[/]")
        return

    display_sessions(sessions, console)


@cli.command()
@click.option("--db", default=":memory:", help="Database file path")
def stats(db: str) -> None:
    """Show index statistics."""
    search_index = SearchIndex(db)
    stats_data = search_index.get_stats()
    display_stats(stats_data, console)


if __name__ == "__main__":
    cli()
