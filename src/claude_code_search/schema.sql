CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    session_path VARCHAR,
    project_directory VARCHAR,
    created_at TIMESTAMP,
    last_message_at TIMESTAMP,
    message_count INTEGER,
    total_cost_usd DECIMAL(10, 6),
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    message_id VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL REFERENCES sessions(session_id),
    sequence_num INTEGER NOT NULL,
    role VARCHAR NOT NULL,
    timestamp TIMESTAMP,
    text_content TEXT,
    thinking_content TEXT,
    cost_usd DECIMAL(10, 6),
    duration_ms INTEGER,
    searchable_text TEXT
);

CREATE TABLE IF NOT EXISTS tool_usages (
    tool_usage_id VARCHAR PRIMARY KEY,
    message_id VARCHAR NOT NULL REFERENCES messages(message_id),
    session_id VARCHAR NOT NULL REFERENCES sessions(session_id),
    tool_name VARCHAR NOT NULL,
    tool_input TEXT,
    tool_result TEXT,
    is_error BOOLEAN DEFAULT FALSE,
    file_path VARCHAR,
    command VARCHAR
);
