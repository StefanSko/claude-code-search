from __future__ import annotations

from pathlib import Path


def test_static_ui_contains_session_dropdown() -> None:
    html_path = (
        Path(__file__).resolve().parents[2] / "src" / "claude_code_search" / "static" / "index.html"
    )
    html = html_path.read_text()

    assert "data-session-dropdown" in html
    assert "Merge sessions" in html
