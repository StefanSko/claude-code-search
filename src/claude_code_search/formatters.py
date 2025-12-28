# ABOUTME: CLI output formatting utilities using Rich library.
# ABOUTME: Provides pretty-printing for search results and statistics.

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table


def display_results(
    results: list[dict[str, Any]], format_type: str = "rich", console: Console | None = None
) -> None:
    """Display search results in the specified format."""
    if console is None:
        console = Console()

    if format_type == "json":
        console.print_json(data=results)
        return

    if format_type == "table":
        table = Table(title="Search Results")
        table.add_column("Session", style="cyan", max_width=12)
        table.add_column("Role", style="magenta", max_width=10)
        table.add_column("Preview", style="white", max_width=60)
        table.add_column("Score", style="green", max_width=8)

        for r in results:
            preview = r.get("text_content", "")[:80]
            if len(r.get("text_content", "")) > 80:
                preview += "..."
            table.add_row(
                str(r.get("session_id", ""))[:12],
                r.get("role", ""),
                preview,
                f"{r.get('score', 0):.3f}",
            )
        console.print(table)
        return

    for r in results:
        session_id = str(r.get("session_id", ""))[:8]
        role = r.get("role", "unknown")
        timestamp = r.get("timestamp", "")
        header = f"[cyan]{session_id}[/] | [magenta]{role}[/] | {timestamp}"

        content = r.get("text_content", "")[:500]
        if len(r.get("text_content", "")) > 500:
            content += "..."

        console.print(Panel(Markdown(content), title=header, border_style="blue"))


def display_stats(stats: dict[str, Any], console: Console | None = None) -> None:
    """Display index statistics."""
    if console is None:
        console = Console()

    table = Table(title="Index Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Sessions indexed", str(stats.get("session_count", 0)))
    table.add_row("Total messages", str(stats.get("message_count", 0)))
    table.add_row("Tool usages", str(stats.get("tool_count", 0)))
    table.add_row("Total cost", f"${stats.get('total_cost_usd', 0):.4f}")

    earliest = stats.get("earliest_message")
    latest = stats.get("latest_message")
    if earliest and latest:
        table.add_row("Date range", f"{earliest} to {latest}")

    console.print(table)


def display_sessions(sessions: list[dict[str, Any]], console: Console | None = None) -> None:
    """Display list of indexed sessions."""
    if console is None:
        console = Console()

    table = Table(title="Indexed Sessions")
    table.add_column("Session ID", style="cyan", max_width=12)
    table.add_column("Project", style="yellow")
    table.add_column("Messages", style="green", justify="right")
    table.add_column("Cost", style="magenta", justify="right")
    table.add_column("Last Updated", style="white")

    for s in sessions:
        table.add_row(
            str(s.get("session_id", ""))[:12],
            s.get("project_directory", "")[:30] or "-",
            str(s.get("message_count", 0)),
            f"${s.get('total_cost_usd', 0):.4f}",
            str(s.get("last_message_at", ""))[:19],
        )

    console.print(table)
