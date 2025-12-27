# Claude Code Transcript Search Tool

## Design Document

**Version:** 0.2  
**Date:** December 2024  
**Status:** Draft

---

## 1. Overview

### 1.1 Problem Statement

Claude Code sessions contain valuable context about coding decisions, prompts, and outcomes. Currently, there's no easy way to search across multiple sessions to find:
- Past solutions to similar problems
- Prompting patterns that worked well
- Specific tool usages or code snippets
- Decision rationale from previous work

### 1.2 Proposed Solution

A CLI tool that:
1. Allows selecting multiple Claude Code sessions (local and/or web)
2. Indexes them into a DuckDB database with full-text search
3. **Launches a local web UI for interactive searching and browsing**
4. Provides CLI query commands for scripting/automation
5. Runs ephemerally via `uvx` with optional persistence

### 1.3 Design Goals

- **Zero installation friction**: Works via `uvx claude-code-search` with no prior setup
- **Interactive exploration**: Browser-based UI for filtering, searching, and browsing
- **Fast iteration**: In-memory by default for quick ad-hoc searches
- **Optional persistence**: Save index to disk for repeated queries
- **Comprehensive search**: Full-text search plus structured field filtering
- **Minimal dependencies**: Leverage DuckDB's built-in capabilities

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CLI Interface                              │
│                    (click + questionary)                             │
└─────────────────────────────────────────────────────────────────────┘
                                   │
         ┌────────────┬────────────┼────────────┬────────────┐
         ▼            ▼            ▼            ▼            ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
   │  index   │ │  serve   │ │  search  │ │   list   │ │  stats   │
   │ command  │ │ command  │ │ command  │ │ command  │ │ command  │
   └──────────┘ └────┬─────┘ └──────────┘ └──────────┘ └──────────┘
         │           │            │
         │           ▼            │
         │    ┌─────────────────────────────────────────────────┐
         │    │              Web UI Layer                        │
         │    │  ┌─────────────┐  ┌───────────────────────────┐ │
         │    │  │ FastAPI     │  │ Frontend (Single HTML)    │ │
         │    │  │ Backend     │◄─┤ - Tailwind CSS            │ │
         │    │  │ /api/*      │  │ - Alpine.js / htmx        │ │
         │    │  └─────────────┘  │ - Real-time search        │ │
         │    │                   └───────────────────────────┘ │
         │    └─────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Session Loader                                │
│  ┌──────────────────┐              ┌──────────────────────────┐    │
│  │ Local Reader     │              │ Web API Client           │    │
│  │ (~/.claude/)     │              │ (api.anthropic.com)      │    │
│  └──────────────────┘              └──────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                        DuckDB Engine                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐ │
│  │   Tables    │  │  FTS Index  │  │  Query Engine               │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────────┘ │
│                                                                     │
│  Storage: :memory: (default) | file.duckdb (persistent)            │
└────────────────────────────────────────────────────────────────────┘
```

### 2.1 Primary User Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  uvx claude-    │     │  Multi-select   │     │  Browser opens  │
│  code-search    │────▶│  sessions in    │────▶│  with search UI │
│                 │     │  terminal       │     │  at :8765       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                              ┌──────────────────────────┘
                              ▼
                 ┌────────────────────────────────┐
                 │         Web UI Features        │
                 │  • Full-text search box        │
                 │  • Filter by session/role/tool │
                 │  • Date range picker           │
                 │  • Expandable message cards    │
                 │  • Syntax-highlighted code     │
                 │  • Export results              │
                 └────────────────────────────────┘
```

---

## 3. Data Model

### 3.1 Source Data Structure

Claude Code sessions are stored as JSONL files with the following message structure:

```jsonc
{
  "uuid": "msg-uuid-here",
  "type": "user" | "assistant" | "system",
  "message": {
    "role": "user" | "assistant",
    "content": [
      { "type": "text", "text": "..." },
      { "type": "tool_use", "id": "...", "name": "bash", "input": {...} },
      { "type": "tool_result", "tool_use_id": "...", "content": "..." }
    ]
  },
  "timestamp": "2024-12-25T10:30:00Z",
  // Assistant messages may include:
  "costUSD": 0.05,
  "durationMs": 1500,
  "thinking": "..." // Extended thinking content
}
```

### 3.2 DuckDB Schema

```sql
-- Sessions table: one row per Claude Code session
CREATE TABLE sessions (
    session_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,           -- 'local' | 'web'
    session_path VARCHAR,              -- File path for local sessions
    project_directory VARCHAR,         -- Working directory if known
    created_at TIMESTAMP,
    last_message_at TIMESTAMP,
    message_count INTEGER,
    total_cost_usd DECIMAL(10, 6),
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Messages table: one row per conversation turn
CREATE TABLE messages (
    message_id VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL REFERENCES sessions(session_id),
    sequence_num INTEGER NOT NULL,     -- Order within session
    role VARCHAR NOT NULL,             -- 'user' | 'assistant' | 'system'
    timestamp TIMESTAMP,
    
    -- Content (denormalized for search efficiency)
    text_content TEXT,                 -- All text content concatenated
    thinking_content TEXT,             -- Extended thinking (assistant only)
    
    -- Metrics (assistant only)
    cost_usd DECIMAL(10, 6),
    duration_ms INTEGER,
    
    -- Searchable combined field
    searchable_text TEXT               -- text_content + thinking_content
);

-- Tool usages table: one row per tool invocation
CREATE TABLE tool_usages (
    tool_usage_id VARCHAR PRIMARY KEY,
    message_id VARCHAR NOT NULL REFERENCES messages(message_id),
    session_id VARCHAR NOT NULL REFERENCES sessions(session_id),
    tool_name VARCHAR NOT NULL,        -- 'bash', 'write', 'edit', 'read', etc.
    tool_input TEXT,                   -- JSON string of input
    tool_result TEXT,                  -- Result/output content
    is_error BOOLEAN DEFAULT FALSE,
    
    -- Extracted fields for common tools
    file_path VARCHAR,                 -- For file operations
    command VARCHAR                    -- For bash operations
);

-- Full-text search indexes
-- DuckDB FTS extension creates these via PRAGMA
```

### 3.3 FTS Configuration

```sql
-- Install and load FTS extension
INSTALL fts;
LOAD fts;

-- Create FTS index on messages
PRAGMA create_fts_index(
    'messages',
    'message_id',
    'text_content', 'thinking_content', 'searchable_text',
    stemmer='english',
    stopwords='english',
    ignore='(\\.|,|!|\\?|\\(|\\)|\\[|\\])'
);

-- Create FTS index on tool usages
PRAGMA create_fts_index(
    'tool_usages',
    'tool_usage_id',
    'tool_input', 'tool_result', 'command', 'file_path',
    stemmer='english',
    stopwords='english'
);
```

---

## 4. CLI Interface

### 4.1 Command Structure

```
claude-code-search [OPTIONS] COMMAND [ARGS]

Commands:
  index     Select and index sessions into DuckDB
  search    Search indexed sessions
  list      List indexed sessions
  stats     Show index statistics
  export    Export search results
```

### 4.2 Command Details

#### Default command (no args) - Index and Serve

```bash
# The most common flow: select sessions, index, and launch UI
uvx claude-code-search

# This is equivalent to:
uvx claude-code-search serve
```

**What happens:**
1. Interactive multi-select picker appears in terminal
2. Selected sessions are indexed into memory (or persistent DB)
3. Browser opens automatically to `http://localhost:8765`
4. Web UI provides interactive search and filtering

#### `serve` - Launch the web UI

```bash
# Interactive session selection, then serve
uvx claude-code-search serve

# Serve with persistent database (skips session selection if DB exists)
uvx claude-code-search serve --db ./my-index.duckdb

# Serve on different port
uvx claude-code-search serve --port 9000

# Don't auto-open browser
uvx claude-code-search serve --no-open

# Re-index before serving (with existing DB)
uvx claude-code-search serve --db ./my-index.duckdb --reindex
```

**Options:**
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | PATH | `:memory:` | Database file path |
| `--port` | INT | `8765` | Port to serve on |
| `--host` | TEXT | `127.0.0.1` | Host to bind to |
| `--no-open` | FLAG | - | Don't open browser automatically |
| `--reindex` | FLAG | - | Re-select and index sessions |
| `--source` | CHOICE | `all` | `local`, `web`, or `all` |

#### `index` - Build or update the search index (CLI only)

```bash
# Interactive multi-select (default)
claude-code-search index

# Index specific sessions by ID
claude-code-search index --session abc123 --session def456

# Index all local sessions
claude-code-search index --all-local

# Index from web sessions
claude-code-search index --source web

# Persist to file
claude-code-search index --db ./my-index.duckdb

# Append to existing index
claude-code-search index --db ./my-index.duckdb --append
```

**Options:**
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | PATH | `:memory:` | Database file path |
| `--source` | CHOICE | `all` | `local`, `web`, or `all` |
| `--session` | TEXT | - | Specific session ID (repeatable) |
| `--all-local` | FLAG | - | Index all local sessions |
| `--all-web` | FLAG | - | Index all web sessions |
| `--append` | FLAG | - | Add to existing index |
| `--since` | TEXT | - | Only sessions after date |
| `--project` | PATH | - | Filter by project directory |

#### `search` - Query the index

```bash
# Full-text search
claude-code-search search "pytest fixtures"

# With filters
claude-code-search search "error handling" --role user
claude-code-search search "async" --tool bash
claude-code-search search "database" --since 2024-12-01

# Search within persistent index
claude-code-search search "api design" --db ./my-index.duckdb

# Output formats
claude-code-search search "refactor" --format json
claude-code-search search "bug fix" --format table
```

**Options:**
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--db` | PATH | `:memory:` | Database file path |
| `--role` | CHOICE | - | Filter by `user` or `assistant` |
| `--tool` | TEXT | - | Filter by tool name |
| `--session` | TEXT | - | Limit to session ID |
| `--since` | TEXT | - | Messages after date |
| `--until` | TEXT | - | Messages before date |
| `--limit` | INT | 20 | Max results |
| `--context` | INT | 0 | Include N surrounding messages |
| `--format` | CHOICE | `rich` | `rich`, `table`, `json`, `csv` |

#### `list` - Show indexed sessions

```bash
claude-code-search list --db ./my-index.duckdb
```

#### `stats` - Index statistics

```bash
claude-code-search stats --db ./my-index.duckdb

# Output example:
# Sessions indexed: 47
# Total messages: 1,234
# Tool usages: 3,456
# Date range: 2024-10-01 to 2024-12-25
# Total cost: $12.34
# Index size: 4.2 MB
```

### 4.3 Interactive Search Mode (Optional Enhancement)

```bash
# Launch interactive REPL
claude-code-search search --interactive --db ./my-index.duckdb

> search: pytest async
Found 12 results...

> filter: tool=bash
Filtered to 5 results...

> context: 2
Showing 2 messages before/after each match...

> export: results.json
Exported to results.json
```

---

## 5. Web UI Design

### 5.1 Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Backend | FastAPI | Async, lightweight, auto-generates OpenAPI docs |
| Frontend | Single HTML + Alpine.js | No build step, works with uvx, reactive |
| Styling | Tailwind CSS (CDN) | No build step, professional look |
| Code highlighting | highlight.js (CDN) | Syntax highlighting for code blocks |

**Why this stack?**
- **Zero build step**: Everything ships as Python + static HTML
- **Works with uvx**: No node_modules, no webpack, no complexity
- **Fast to iterate**: Hot reload during development
- **Small bundle**: Single HTML file with CDN dependencies

### 5.2 UI Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🔍 Claude Code Search                              [Export ▼] [⚙️]     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 🔎 Search across all sessions...                        [Search]│   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────┐  ┌──────────────────────────────────────────┐│
│  │ FILTERS              │  │ RESULTS                        47 found ││
│  │                      │  │                                         ││
│  │ Sessions             │  │ ┌─────────────────────────────────────┐ ││
│  │ ┌──────────────────┐ │  │ │ 📁 abc12345 · 2h ago                │ ││
│  │ │ ☑ abc12345 (12)  │ │  │ │ User: Create a Python CLI for...   │ ││
│  │ │ ☑ def67890 (8)   │ │  │ │                                     │ ││
│  │ │ ☐ ghi11111 (3)   │ │  │ │ Match: "I'll create a **CLI** using│ ││
│  │ └──────────────────┘ │  │ │ Click for the interface..."         │ ││
│  │                      │  │ │                          [View Full] │ ││
│  │ Role                 │  │ └─────────────────────────────────────┘ ││
│  │ ○ All                │  │                                         ││
│  │ ○ User               │  │ ┌─────────────────────────────────────┐ ││
│  │ ○ Assistant          │  │ │ 📁 def67890 · 1d ago                │ ││
│  │                      │  │ │ Assistant: Here's the fix for the   │ ││
│  │ Tool                 │  │ │ authentication bug...               │ ││
│  │ ┌──────────────────┐ │  │ │                                     │ ││
│  │ │ All tools      ▼ │ │  │ │ 🔧 bash: pytest tests/             │ ││
│  │ └──────────────────┘ │  │ └─────────────────────────────────────┘ ││
│  │                      │  │                                         ││
│  │ Date Range           │  │ ┌─────────────────────────────────────┐ ││
│  │ [From: ____] [To: __]│  │ │ 📁 abc12345 · 2h ago                │ ││
│  │                      │  │ │ ...more results...                  │ ││
│  │ ──────────────────── │  │ └─────────────────────────────────────┘ ││
│  │                      │  │                                         ││
│  │ Stats                │  │          [Load More Results]            ││
│  │ 3 sessions indexed   │  │                                         ││
│  │ 23 messages          │  └──────────────────────────────────────────┘│
│  │ 45 tool calls        │                                              │
│  │ $1.23 total cost     │                                              │
│  └──────────────────────┘                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Expanded Message View (Modal)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Message from session abc12345                                    [✕]  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─── User ─────────────────────────────────────────── 10:30 AM ─────┐ │
│  │ Create a Python CLI for searching files with support for regex    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─── Assistant ($0.02 · 3.5s) ──────────────────────── 10:30 AM ────┐ │
│  │                                                                    │ │
│  │  💭 Thinking                                            [Expand ▼] │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ The user wants a file search CLI. I should use Click for    │ │ │
│  │  │ the interface and pathlib for file operations. For regex... │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  I'll create a CLI using Click that supports regex pattern        │ │
│  │  matching. Here's the implementation:                             │ │
│  │                                                                    │ │
│  │  🔧 Tool: write → cli.py                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ ```python                                                    │ │ │
│  │  │ import click                                                 │ │ │
│  │  │ import re                                                    │ │ │
│  │  │ from pathlib import Path                                     │ │ │
│  │  │                                                              │ │ │
│  │  │ @click.command()                                             │ │ │
│  │  │ @click.argument('pattern')                                   │ │ │
│  │  │ def search(pattern):                                         │ │ │
│  │  │     ...                                                      │ │ │
│  │  │ ```                                                          │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  ✅ Result: File written successfully                             │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─── Context: 2 messages before ────────────────────────────────────┐ │
│  │ [Show previous context]                                           │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│                              [Copy Message] [View in Session]           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.4 API Endpoints

```
GET  /api/stats
     Returns index statistics (session count, message count, etc.)

GET  /api/sessions
     Returns list of indexed sessions with metadata

GET  /api/sessions/{session_id}
     Returns full session with all messages

GET  /api/search?q=<query>&role=<role>&tool=<tool>&session=<id>&limit=<n>
     Full-text search with filters
     Returns: { results: [...], total: n, query_time_ms: n }

GET  /api/search/tools?q=<query>&tool_name=<name>
     Search within tool usages specifically

GET  /api/messages/{message_id}
     Returns single message with full context

GET  /api/messages/{message_id}/context?before=<n>&after=<n>
     Returns message with surrounding context

GET  /api/export?format=<json|csv>&q=<query>&...
     Export search results

GET  /
     Serves the single-page HTML application
```

### 5.5 Frontend Implementation

#### HTML Structure (templates/index.html)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Code Search</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
</head>
<body class="bg-gray-900 text-gray-100">
    <div x-data="searchApp()" x-init="init()" class="min-h-screen">
        <!-- Header -->
        <header class="border-b border-gray-700 px-6 py-4">
            <div class="flex items-center justify-between">
                <h1 class="text-xl font-semibold">🔍 Claude Code Search</h1>
                <div class="flex gap-2">
                    <button @click="exportResults()" class="btn-secondary">Export</button>
                    <button @click="showStats = true" class="btn-secondary">Stats</button>
                </div>
            </div>
        </header>

        <!-- Search Bar -->
        <div class="px-6 py-4">
            <div class="flex gap-2">
                <input 
                    type="text" 
                    x-model="query"
                    @keyup.enter="search()"
                    @input.debounce.300ms="search()"
                    placeholder="Search across all sessions..."
                    class="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2"
                >
                <button @click="search()" class="btn-primary">Search</button>
            </div>
        </div>

        <!-- Main Content -->
        <div class="flex px-6 gap-6">
            <!-- Filters Sidebar -->
            <aside class="w-64 flex-shrink-0">
                <!-- Filter components -->
            </aside>

            <!-- Results -->
            <main class="flex-1">
                <template x-for="result in results" :key="result.message_id">
                    <div class="result-card" @click="showMessage(result)">
                        <!-- Result card content -->
                    </div>
                </template>
            </main>
        </div>

        <!-- Message Modal -->
        <div x-show="selectedMessage" class="modal-overlay">
            <!-- Full message view -->
        </div>
    </div>

    <script>
        function searchApp() {
            return {
                query: '',
                results: [],
                filters: { role: null, tool: null, sessions: [] },
                sessions: [],
                stats: {},
                selectedMessage: null,
                loading: false,

                async init() {
                    this.stats = await fetch('/api/stats').then(r => r.json());
                    this.sessions = await fetch('/api/sessions').then(r => r.json());
                },

                async search() {
                    if (!this.query.trim()) {
                        this.results = [];
                        return;
                    }
                    this.loading = true;
                    const params = new URLSearchParams({ q: this.query, ...this.filters });
                    this.results = await fetch(`/api/search?${params}`).then(r => r.json());
                    this.loading = false;
                },

                async showMessage(result) {
                    const msg = await fetch(`/api/messages/${result.message_id}/context?before=2&after=2`)
                        .then(r => r.json());
                    this.selectedMessage = msg;
                },

                // ... more methods
            }
        }
    </script>
</body>
</html>
```

### 5.6 Real-Time Search UX

The search experience should feel instant:

1. **Debounced input**: Search triggers 300ms after typing stops
2. **Loading states**: Skeleton loaders while fetching
3. **Highlighted matches**: Search terms highlighted in results
4. **Keyboard navigation**: Arrow keys to navigate results, Enter to expand
5. **URL state**: Query params reflect current search (shareable/bookmarkable)

```javascript
// Highlight matching terms in results
function highlightMatches(text, query) {
    const terms = query.split(/\s+/).filter(t => t.length > 2);
    let highlighted = text;
    for (const term of terms) {
        const regex = new RegExp(`(${escapeRegex(term)})`, 'gi');
        highlighted = highlighted.replace(regex, '<mark>$1</mark>');
    }
    return highlighted;
}
```

### 5.7 Session Picker Integration

When launching without a persistent DB, the terminal shows an interactive picker:

```
╭─────────────────────────────────────────────────────────────────────────╮
│  Select sessions to index (Space to toggle, Enter to confirm)          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ◉ abc12345  2 hours ago   "Create a Python CLI for..."    12 msgs    │
│  ◉ def67890  1 day ago     "Fix authentication bug..."     8 msgs     │
│  ○ ghi11111  3 days ago    "Add database migrations..."    45 msgs    │
│  ○ jkl22222  1 week ago    "Refactor API endpoints..."     23 msgs    │
│                                                                         │
│  [a] Select all  [n] Select none  [/] Filter  [Enter] Confirm          │
╰─────────────────────────────────────────────────────────────────────────╯
```

After confirmation:
```
Indexing 2 sessions...
  ✓ abc12345 (12 messages, 34 tool calls)
  ✓ def67890 (8 messages, 12 tool calls)

Index created: 20 messages, 46 tool calls
Starting server at http://localhost:8765

Opening browser...
```

---

## 6. Implementation Details

### 5.1 Session Discovery

#### Local Sessions
```python
from pathlib import Path
import json

def discover_local_sessions() -> list[dict]:
    """Find all local Claude Code sessions."""
    sessions_dir = Path.home() / ".claude" / "sessions"
    sessions = []
    
    for session_dir in sessions_dir.iterdir():
        if session_dir.is_dir():
            # Read session metadata
            messages_file = session_dir / "messages.jsonl"
            if messages_file.exists():
                sessions.append({
                    "id": session_dir.name,
                    "path": str(messages_file),
                    "source": "local",
                    "modified": messages_file.stat().st_mtime
                })
    
    return sorted(sessions, key=lambda s: s["modified"], reverse=True)
```

#### Web Sessions
```python
import subprocess
import json
import httpx

def get_oauth_token() -> str:
    """Extract OAuth token from macOS Keychain."""
    result = subprocess.run(
        ["security", "find-generic-password", "-a", os.environ["USER"], 
         "-w", "-s", "Claude Code-credentials"],
        capture_output=True, text=True
    )
    creds = json.loads(result.stdout)
    return creds["claudeAiOauth"]["accessToken"]

def get_org_uuid() -> str:
    """Get organization UUID from Claude config."""
    config_path = Path.home() / ".claude.json"
    config = json.loads(config_path.read_text())
    return config["oauthAccount"]["organizationUuid"]

def fetch_web_sessions() -> list[dict]:
    """Fetch sessions from Claude Code for web."""
    token = get_oauth_token()
    org_uuid = get_org_uuid()
    
    response = httpx.get(
        "https://api.anthropic.com/v1/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "x-organization-uuid": org_uuid,
        }
    )
    return response.json()["sessions"]
```

### 5.2 Message Parsing

```python
def parse_message(raw: dict, session_id: str, seq: int) -> tuple[dict, list[dict]]:
    """Parse a raw message into structured data."""
    message = {
        "message_id": raw.get("uuid", f"{session_id}-{seq}"),
        "session_id": session_id,
        "sequence_num": seq,
        "role": raw.get("message", {}).get("role", raw.get("type")),
        "timestamp": raw.get("timestamp"),
        "cost_usd": raw.get("costUSD"),
        "duration_ms": raw.get("durationMs"),
        "thinking_content": raw.get("thinking"),
    }
    
    # Extract text content and tool usages
    text_parts = []
    tool_usages = []
    
    content = raw.get("message", {}).get("content", [])
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_usages.append({
                    "tool_usage_id": block.get("id"),
                    "message_id": message["message_id"],
                    "session_id": session_id,
                    "tool_name": block.get("name"),
                    "tool_input": json.dumps(block.get("input", {})),
                    "file_path": extract_file_path(block),
                    "command": extract_command(block),
                })
            elif block.get("type") == "tool_result":
                # Match to existing tool usage and add result
                tool_id = block.get("tool_use_id")
                for tu in tool_usages:
                    if tu["tool_usage_id"] == tool_id:
                        tu["tool_result"] = str(block.get("content", ""))
                        tu["is_error"] = block.get("is_error", False)
    
    message["text_content"] = "\n".join(text_parts)
    message["searchable_text"] = "\n".join(filter(None, [
        message["text_content"],
        message["thinking_content"]
    ]))
    
    return message, tool_usages

def extract_file_path(block: dict) -> str | None:
    """Extract file path from tool input."""
    tool_input = block.get("input", {})
    return tool_input.get("path") or tool_input.get("file_path")

def extract_command(block: dict) -> str | None:
    """Extract command from bash tool input."""
    if block.get("name") == "bash":
        return block.get("input", {}).get("command")
    return None
```

### 5.3 DuckDB Integration

```python
import duckdb

class SearchIndex:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = duckdb.connect(db_path)
        self._init_schema()
    
    def _init_schema(self):
        """Initialize database schema and FTS."""
        self.conn.execute("INSTALL fts; LOAD fts;")
        
        # Create tables (see schema in section 3.2)
        self.conn.execute(SESSIONS_TABLE_DDL)
        self.conn.execute(MESSAGES_TABLE_DDL)
        self.conn.execute(TOOL_USAGES_TABLE_DDL)
    
    def index_session(self, session_id: str, messages: list[dict]):
        """Index a single session."""
        # Insert session metadata
        self.conn.execute("""
            INSERT INTO sessions (session_id, source, ...)
            VALUES (?, ?, ...)
        """, [...])
        
        # Insert messages and tool usages
        for seq, raw_msg in enumerate(messages):
            msg, tools = parse_message(raw_msg, session_id, seq)
            self.conn.execute("INSERT INTO messages ...", msg)
            self.conn.executemany("INSERT INTO tool_usages ...", tools)
        
        # Rebuild FTS index
        self._rebuild_fts()
    
    def _rebuild_fts(self):
        """Rebuild full-text search indexes."""
        self.conn.execute("""
            PRAGMA create_fts_index(
                'messages', 'message_id',
                'searchable_text',
                stemmer='english',
                stopwords='english',
                overwrite=1
            )
        """)
    
    def search(self, query: str, **filters) -> list[dict]:
        """Execute a search query."""
        sql = """
            WITH matches AS (
                SELECT *, fts_main_messages.match_bm25(
                    message_id, ?, fields := 'searchable_text'
                ) AS score
                FROM messages
                WHERE score IS NOT NULL
            )
            SELECT m.*, s.project_directory
            FROM matches m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE 1=1
        """
        params = [query]
        
        if filters.get("role"):
            sql += " AND m.role = ?"
            params.append(filters["role"])
        
        if filters.get("since"):
            sql += " AND m.timestamp >= ?"
            params.append(filters["since"])
        
        sql += " ORDER BY score DESC LIMIT ?"
        params.append(filters.get("limit", 20))
        
        return self.conn.execute(sql, params).fetchall()
    
    def search_tools(self, query: str, tool_name: str = None) -> list[dict]:
        """Search within tool usages."""
        sql = """
            SELECT *, fts_main_tool_usages.match_bm25(
                tool_usage_id, ?, fields := 'tool_input,tool_result,command'
            ) AS score
            FROM tool_usages
            WHERE score IS NOT NULL
        """
        params = [query]
        
        if tool_name:
            sql += " AND tool_name = ?"
            params.append(tool_name)
        
        sql += " ORDER BY score DESC LIMIT 20"
        
        return self.conn.execute(sql, params).fetchall()
```

### 6.4 Rich Output Formatting

```python
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich.panel import Panel
from rich.markdown import Markdown

def display_results(results: list[dict], format: str = "rich"):
    console = Console()
    
    if format == "json":
        console.print_json(data=results)
        return
    
    if format == "table":
        table = Table(title="Search Results")
        table.add_column("Session", style="cyan")
        table.add_column("Role", style="magenta")
        table.add_column("Preview", style="white")
        table.add_column("Score", style="green")
        
        for r in results:
            table.add_row(
                r["session_id"][:8],
                r["role"],
                r["text_content"][:80] + "...",
                f"{r['score']:.3f}"
            )
        console.print(table)
        return
    
    # Rich format (default)
    for r in results:
        header = f"[cyan]{r['session_id'][:8]}[/] | [magenta]{r['role']}[/] | {r['timestamp']}"
        content = r["text_content"][:500]
        if len(r["text_content"]) > 500:
            content += "..."
        
        console.print(Panel(
            Markdown(content),
            title=header,
            border_style="blue"
        ))
```

### 6.5 FastAPI Server Implementation

```python
# server/app.py
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
import webbrowser
import uvicorn

from ..index import SearchIndex

app = FastAPI(title="Claude Code Search")
index: SearchIndex = None  # Injected at startup

# Serve static frontend
STATIC_DIR = Path(__file__).parent.parent / "static"

@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/stats")
async def get_stats():
    return index.get_stats()

@app.get("/api/sessions")
async def list_sessions():
    return index.list_sessions()

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    return index.get_session(session_id)

@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1),
    role: str = Query(None),
    tool: str = Query(None),
    session: str = Query(None),
    since: str = Query(None),
    until: str = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    results = index.search(
        query=q,
        role=role,
        tool=tool,
        session_id=session,
        since=since,
        until=until,
        limit=limit,
    )
    return {
        "results": results,
        "total": len(results),
        "query": q,
    }

@app.get("/api/messages/{message_id}")
async def get_message(message_id: str):
    return index.get_message(message_id)

@app.get("/api/messages/{message_id}/context")
async def get_message_context(
    message_id: str,
    before: int = Query(2, ge=0, le=10),
    after: int = Query(2, ge=0, le=10),
):
    return index.get_message_with_context(message_id, before, after)

@app.get("/api/export")
async def export_results(
    format: str = Query("json", regex="^(json|csv)$"),
    q: str = Query(...),
    **filters
):
    results = index.search(query=q, **filters, limit=1000)
    if format == "csv":
        # Return CSV response
        pass
    return results


def run_server(search_index: SearchIndex, host: str, port: int, open_browser: bool):
    """Start the web server with the given index."""
    global index
    index = search_index
    
    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    
    uvicorn.run(app, host=host, port=port, log_level="warning")
```

### 6.6 CLI Serve Command

```python
# cli.py
import click
from .index import SearchIndex
from .loaders import discover_sessions, load_session
from .server.app import run_server
import questionary

@click.command()
@click.option('--db', default=':memory:', help='Database path')
@click.option('--port', default=8765, help='Port to serve on')
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.option('--no-open', is_flag=True, help="Don't open browser")
@click.option('--reindex', is_flag=True, help='Re-select sessions')
@click.option('--source', type=click.Choice(['local', 'web', 'all']), default='all')
def serve(db, port, host, no_open, reindex, source):
    """Launch the web UI for searching sessions."""
    
    index = SearchIndex(db)
    
    # Check if we need to index
    needs_indexing = db == ':memory:' or reindex or index.is_empty()
    
    if needs_indexing:
        # Discover available sessions
        sessions = discover_sessions(source=source)
        
        # Interactive multi-select
        choices = [
            questionary.Choice(
                title=f"{s['id'][:8]}  {s['age']}  \"{s['preview']}\"  {s['count']} msgs",
                value=s['id'],
                checked=True  # Default to selected
            )
            for s in sessions[:50]  # Limit for UX
        ]
        
        selected = questionary.checkbox(
            "Select sessions to index (Space to toggle, Enter to confirm):",
            choices=choices,
        ).ask()
        
        if not selected:
            click.echo("No sessions selected. Exiting.")
            return
        
        # Index selected sessions
        click.echo(f"Indexing {len(selected)} sessions...")
        for session_id in selected:
            messages = load_session(session_id, source)
            index.index_session(session_id, messages)
            click.echo(f"  ✓ {session_id[:8]}")
        
        stats = index.get_stats()
        click.echo(f"\nIndex created: {stats['message_count']} messages, {stats['tool_count']} tool calls")
    
    click.echo(f"\nStarting server at http://{host}:{port}")
    run_server(index, host, port, open_browser=not no_open)
```

---

## 7. Project Structure

```
claude-code-search/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── claude_code_search/
│       ├── __init__.py
│       ├── __main__.py          # Entry point
│       ├── cli.py               # Click commands
│       ├── index.py             # SearchIndex class
│       ├── loaders/
│       │   ├── __init__.py
│       │   ├── base.py          # Abstract loader
│       │   ├── local.py         # Local session loader
│       │   └── web.py           # Web API loader
│       ├── parsers.py           # Message parsing
│       ├── formatters.py        # CLI output formatting
│       ├── schema.sql           # DDL statements
│       │
│       ├── server/              # Web UI backend
│       │   ├── __init__.py
│       │   ├── app.py           # FastAPI application
│       │   ├── routes.py        # API endpoints
│       │   └── models.py        # Pydantic models for API
│       │
│       └── static/              # Web UI frontend
│           └── index.html       # Single-page application
│
└── tests/
    ├── conftest.py
    ├── test_cli.py
    ├── test_index.py
    ├── test_loaders.py
    ├── test_parsers.py
    ├── test_server.py           # API endpoint tests
    └── fixtures/
        └── sample_session.jsonl
```

---

## 8. Dependencies

### Runtime Dependencies

```toml
[project]
dependencies = [
    # CLI
    "click>=8.0",
    "click-default-group>=1.2",
    "questionary>=2.0",
    "rich>=13.0",
    
    # Database
    "duckdb>=1.0",
    
    # HTTP client (for web sessions)
    "httpx>=0.27",
    
    # Web UI server
    "fastapi>=0.110",
    "uvicorn>=0.27",
]
```

### Development Dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpx>=0.30",
    "pytest-asyncio>=0.23",   # For testing FastAPI
    "httpx>=0.27",             # For TestClient
    "syrupy>=4.0",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

### pyproject.toml Script Entry

```toml
[project.scripts]
claude-code-search = "claude_code_search.cli:cli"
```

---

## 9. Example Usage Flows

### Flow 1: Quick Interactive Search (Default)

```bash
# Just run it - the default experience
$ uvx claude-code-search

# Terminal shows session picker:
# ◉ abc12345  2 hours ago   "Create a Python CLI..."    12 msgs
# ◉ def67890  1 day ago     "Fix auth bug..."           8 msgs
# (press Enter to confirm)

Indexing 2 sessions...
  ✓ abc12345 (12 messages)
  ✓ def67890 (8 messages)

Starting server at http://localhost:8765
Opening browser...

# Browser opens with the search UI
# Search, filter, browse interactively
# Ctrl+C to stop the server
```

### Flow 2: Persistent Index with Web UI

```bash
# First time: select sessions and create persistent index
$ uvx claude-code-search serve --db ~/search-index.duckdb

# Later: just serve the existing index (no session picker)
$ uvx claude-code-search serve --db ~/search-index.duckdb

# Add new sessions to existing index
$ uvx claude-code-search serve --db ~/search-index.duckdb --reindex
```

### Flow 3: CLI-Only Search (Scripting/Automation)

```bash
# Index and search without UI (for scripts, CI, etc.)
$ uvx claude-code-search index --all-local --db ./index.duckdb
$ uvx claude-code-search search "authentication" --db ./index.duckdb --format json

# Pipe to jq for processing
$ uvx claude-code-search search "bug fix" --db ./index.duckdb --format json | jq '.[].text_content'
```

### Flow 4: Project-Specific Index

```bash
# Build persistent index for a project
$ uvx claude-code-search serve \
    --project ~/code/myproject \
    --db ~/code/myproject/.claude-search.duckdb

# The index lives with your project
$ cd ~/code/myproject
$ uvx claude-code-search serve --db .claude-search.duckdb
```

### Flow 5: Tool-Specific Search (via UI or CLI)

```bash
# In the web UI: use the Tool dropdown filter

# Via CLI:
$ uvx claude-code-search search "docker" --tool bash --db ./index.duckdb
$ uvx claude-code-search search "test_*.py" --tool edit --db ./index.duckdb
```

---

## 10. Future Enhancements

### Phase 2 Considerations

1. **Semantic search**: Add optional embedding-based search using DuckDB's VSS extension
2. **Saved searches**: Save and name frequently used queries
3. **Export to HTML**: Generate shareable HTML reports (like Simon's tool)
4. **Session diffing**: Compare two sessions to see what changed
5. **Cost analytics dashboard**: Track spending patterns across sessions with visualizations
6. **Integration with `claude-code-transcripts`**: Import/export compatibility
7. **Real-time indexing**: Watch for new sessions and auto-index

### Technical Debt to Address

1. Handle very large sessions (>10k messages) with streaming inserts
2. Add progress bars for long indexing operations
3. Support Windows (keychain access differs)
4. Add session deduplication for re-indexing
5. WebSocket support for live search updates

---

## 11. Open Questions

1. **Session ID stability**: Are local session IDs stable across machines? (Affects syncing)
2. **Web API rate limits**: What are the limits on the sessions API?
3. **Thinking content availability**: Is thinking always present in web sessions?
4. **Multi-user support**: Should the index support multiple Claude accounts?

---

## Appendix A: DuckDB FTS Capabilities

DuckDB's FTS extension supports:
- BM25 ranking
- Stemming (porter, english, etc.)
- Stop word filtering
- Phrase queries: `"exact phrase"`
- Boolean operators: `term1 AND term2`, `term1 OR term2`
- Prefix matching: `prefix*`

Query example:
```sql
SELECT *, fts_main_messages.match_bm25(
    message_id,
    'python AND (async OR await)',
    fields := 'searchable_text'
) AS score
FROM messages
WHERE score IS NOT NULL
ORDER BY score DESC;
```

---

## Appendix B: Sample Session JSON

```json
{"uuid":"msg-001","type":"user","message":{"role":"user","content":"Create a Python CLI for searching files"},"timestamp":"2024-12-25T10:00:00Z"}
{"uuid":"msg-002","type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"I'll create a CLI using Click..."},{"type":"tool_use","id":"tool-001","name":"write","input":{"path":"cli.py","content":"import click..."}}]},"timestamp":"2024-12-25T10:00:05Z","costUSD":0.02,"durationMs":3500,"thinking":"The user wants a file search CLI. I should use Click for the interface and pathlib for file operations..."}
{"uuid":"msg-003","type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool-001","content":"File written successfully"}]},"timestamp":"2024-12-25T10:00:06Z"}
```
