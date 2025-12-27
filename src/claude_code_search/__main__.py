# ABOUTME: Entry point for running claude-code-search as a module.
# ABOUTME: Allows running via `python -m claude_code_search`.

from claude_code_search.cli import cli

if __name__ == "__main__":
    cli()
