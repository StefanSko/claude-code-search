from __future__ import annotations

import csv
import io
import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def format_results(results: list[dict[str, Any]], output_format: str) -> str | None:
    if output_format == "json":
        return json.dumps(results, ensure_ascii=True, default=str)
    if output_format == "csv":
        return _results_to_csv(results)
    return None


def render_results(results: list[dict[str, Any]]) -> None:
    console = Console()
    for result in results:
        header = f"{result['session_id'][:8]} | {result['role']}"
        content = result.get("text_content") or ""
        if len(content) > 500:
            content = f"{content[:500]}..."
        console.print(Panel(content, title=header, border_style="cyan"))


def render_results_table(results: list[dict[str, Any]]) -> None:
    console = Console()
    table = Table(title="Search Results")
    table.add_column("Session", style="cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Preview", style="white")
    table.add_column("Score", style="green")

    for result in results:
        preview = (result.get("text_content") or "")[:80]
        table.add_row(
            result.get("session_id", "")[:8],
            result.get("role", ""),
            preview,
            f"{result.get('score', 0.0):.3f}",
        )
    console.print(table)


def _results_to_csv(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)
    return output.getvalue()
