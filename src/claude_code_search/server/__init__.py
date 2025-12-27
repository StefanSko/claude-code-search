# ABOUTME: Web UI server package for Claude Code Search.
# ABOUTME: Provides FastAPI application and API endpoints.

from claude_code_search.server.app import create_app, run_server

__all__ = ["create_app", "run_server"]
