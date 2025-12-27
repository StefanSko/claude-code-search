# Claude Code Search

A full-text search tool for Claude Code sessions. Index your conversations, search across them with BM25 ranking, and browse results through an interactive web UI.

## Features

- **Full-text search** with BM25 ranking across all your Claude Code sessions
- **Interactive web UI** for browsing search results with message context
- **CLI interface** for scripted searches and automation
- **Content type filtering** - filter by text, tool calls, or thinking content
- **Role filtering** - filter by user or assistant messages
- **Message context** - view surrounding messages (prev/next) for any search result
- **Cost tracking** - see API costs per message and session

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/claude-code-search.git
cd claude-code-search

# Install with uv
uv sync
```

## Quick Start

### Web UI (Recommended)

Launch the web interface - this will prompt you to select sessions to index:

```bash
uv run claude-code-search
```

Or explicitly:

```bash
uv run claude-code-search serve
```

Options:
- `--port PORT` - Port to serve on (default: 8765)
- `--host HOST` - Host to bind to (default: 127.0.0.1)
- `--no-open` - Don't open browser automatically
- `--reindex` - Re-select and index sessions
- `--db PATH` - Persist index to a database file

### CLI Search

First, build an index:

```bash
# Interactive selection
uv run claude-code-search index --db ./search.db

# Index all local sessions
uv run claude-code-search index --db ./search.db --all-local
```

Then search:

```bash
# Basic search
uv run claude-code-search search "Python CLI" --db ./search.db

# Filter by role
uv run claude-code-search search "error" --db ./search.db --role assistant

# Output as JSON
uv run claude-code-search search "config" --db ./search.db --format json

# Limit results
uv run claude-code-search search "test" --db ./search.db --limit 5
```

### Other Commands

```bash
# List indexed sessions
uv run claude-code-search list --db ./search.db

# Show index statistics
uv run claude-code-search stats --db ./search.db
```

## Web UI Features

### Search Filters

- **Sessions** - Filter results to specific sessions
- **Role** - All / User / Assistant
- **Content** - All / Text / Tool (filter by message type)

### Message Context

Click any search result to see:
- The matched message (highlighted)
- 2 messages before and after for context
- Thinking content (collapsible)
- Tool usage summaries for tool-only messages

### Export

Click "Export" to download search results as JSON.

## Message Types

The search index classifies messages into types:

| Type | Description |
|------|-------------|
| `text` | Regular conversation messages |
| `tool_use` | Assistant invoking tools (Write, Bash, etc.) |
| `tool_result` | Tool output returned to conversation |
| `thinking` | Extended thinking content only |
| `system` | System messages (file snapshots, etc.) |

For messages without text content (e.g., pure tool calls), the UI shows a summary:
- Tool use: `Write: path/to/file.py | Bash: npm install...`
- Tool result: Preview of the result content
- Thinking: Preview of thinking content

## API Endpoints

When running the server, these endpoints are available:

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /api/stats` | Index statistics |
| `GET /api/sessions` | List all sessions |
| `GET /api/sessions/{id}` | Get session with messages |
| `GET /api/search?q=...` | Full-text search |
| `GET /api/messages/{id}` | Get single message |
| `GET /api/messages/{id}/context` | Get message with surrounding context |

### Search Parameters

- `q` (required) - Search query
- `role` - Filter by role (user/assistant)
- `content_type` - Filter by content type (text/tool)
- `session` - Limit to session ID
- `since` / `until` - Date range filters
- `limit` - Max results (default: 20)

## Development

### Run Tests

```bash
uv run pytest tests/ -v
```

### Project Structure

```
src/claude_code_search/
├── cli.py           # Click CLI commands
├── index.py         # DuckDB search index
├── parsers.py       # Message parsing from JSONL
├── formatters.py    # CLI output formatting
├── loaders/         # Session loaders
│   ├── base.py      # Abstract loader
│   └── local.py     # Local ~/.claude/projects loader
├── server/
│   ├── app.py       # FastAPI application
│   └── models.py    # Pydantic models
└── static/
    └── index.html   # Web UI (Alpine.js + Tailwind)
```

## License

MIT
