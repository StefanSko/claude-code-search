# Claude Code Search

A full-text search tool for Claude Code sessions. Index your conversations, search across them with BM25 ranking, and browse results through an interactive web UI.

## Features

- **Full-text search** with BM25 ranking across all your Claude Code sessions
- **Hierarchical interaction view** - group messages into logical user-assistant exchanges
- **Commit tracking** - automatic extraction of git commits from tool outputs
- **Interactive web UI** for browsing search results with message context
- **CLI interface** for scripted searches and automation
- **Content type filtering** - filter by text, tool calls, or thinking content
- **Role filtering** - filter by user or assistant messages
- **Message context** - view surrounding messages (prev/next) for any search result
- **Cost tracking** - see API costs per message and session
- **Export** - download search results as JSON

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

### View Modes

Toggle between two view modes using the buttons in the header:

#### Messages View
Traditional flat list of messages matching your search query:
- Shows individual messages with role badges (user/assistant)
- Content type indicators for tool calls and results
- Score ranking from BM25 search
- Click to see full message with surrounding context

#### Interactions View
Hierarchical view grouping messages into logical exchanges:
- Each interaction represents a complete user prompt and assistant response cycle
- Includes all tool calls and results within that exchange
- Shows commits made during the interaction
- Displays thinking indicator when extended thinking was used
- Shows total cost for the interaction

### Interaction Cards

Each interaction card displays:
- **Session ID** - Truncated identifier (click to see full)
- **Timestamp** - When the interaction started
- **Thinking indicator** (💭) - Shown if extended thinking was used
- **Cost** - Total API cost for the interaction
- **User prompt** - The user's question or request (highlighted if matched)
- **Tool badges** - List of tools used (Write, Bash, Read, etc.)
- **Commit badges** - Git commits made during this interaction (click to copy hash)

### Interaction Modal

Click an interaction to open the full view:
- **Navigation** - Use ◀/▶ buttons or arrow keys to browse interactions
- **User prompt section** - Full text of the user's request
- **Message timeline** - All messages in the interaction with:
  - Role badges and timestamps
  - Collapsible thinking content (💭 Thinking ▶)
  - Text content or tool summaries
  - Cost per message
- **Commits section** - All commits with:
  - Full commit hash (click to copy)
  - Commit message
  - Branch name
- **Footer stats** - Message count, tool count, commit count
- **Copy All** - Copy the entire interaction to clipboard

### Search Filters

- **Sessions** - Filter results to specific sessions
- **Role** - All / User / Assistant
- **Content** - All / Text / Tool (filter by message type)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Submit search |
| `Escape` | Close modal |
| `←` | Previous interaction (in modal) |
| `→` | Next interaction (in modal) |

### Commit Features

- **Automatic extraction** - Commits are parsed from `git commit` tool results
- **HEREDOC support** - Handles Claude Code's multi-line commit messages
- **Click to copy** - Click any commit hash to copy to clipboard
- **Branch tracking** - Shows which branch the commit was made on

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

### Core Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /api/stats` | Index statistics |
| `GET /api/sessions` | List all sessions |
| `GET /api/sessions/{id}` | Get session with messages |
| `GET /api/search?q=...` | Full-text search (messages) |
| `GET /api/messages/{id}` | Get single message |
| `GET /api/messages/{id}/context` | Get message with surrounding context |

### Interaction Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/interactions/{session_id}` | Get all interactions for a session |
| `GET /api/interaction/{id}` | Get single interaction with messages and commits |
| `GET /api/search/interactions?q=...` | Full-text search (interaction level) |

### Commit Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/commits/{hash}` | Get commit details by hash |
| `GET /api/search/commits?q=...` | Search commits by hash or message |

### Search Parameters

**Message search** (`/api/search`):
- `q` (required) - Search query
- `role` - Filter by role (user/assistant)
- `content_type` - Filter by content type (text/tool)
- `session` - Limit to session ID
- `since` / `until` - Date range filters
- `limit` - Max results (default: 20)

**Interaction search** (`/api/search/interactions`):
- `q` (required) - Search query
- `session` - Filter by session ID
- `limit` - Max results (default: 20)

**Commit search** (`/api/search/commits`):
- `q` (required) - Search query (matches hash or message)
- `session` - Filter by session ID
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
