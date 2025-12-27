# ABOUTME: Pydantic models for API request/response validation.
# ABOUTME: Defines data schemas for search results, sessions, and messages.

from pydantic import BaseModel, Field


class StatsResponse(BaseModel):
    """Index statistics response."""

    session_count: int
    message_count: int
    tool_count: int
    total_cost_usd: float
    earliest_message: str | None
    latest_message: str | None


class SessionSummary(BaseModel):
    """Summary of an indexed session."""

    session_id: str
    source: str
    project_directory: str | None
    created_at: str | None
    last_message_at: str | None
    message_count: int
    total_cost_usd: float | None


class ToolUsageResponse(BaseModel):
    """Tool usage details."""

    tool_usage_id: str
    message_id: str
    session_id: str
    tool_name: str
    tool_input: str | None
    tool_result: str | None
    is_error: bool
    file_path: str | None
    command: str | None


class MessageResponse(BaseModel):
    """Message details with optional tool usages."""

    message_id: str
    session_id: str
    sequence_num: int
    role: str
    timestamp: str | None
    text_content: str | None
    thinking_content: str | None
    cost_usd: float | None
    duration_ms: int | None
    tool_usages: list[ToolUsageResponse] = Field(default_factory=list)


class SearchResult(BaseModel):
    """A single search result."""

    message_id: str
    session_id: str
    role: str
    timestamp: str | None
    text_content: str | None
    thinking_content: str | None
    project_directory: str | None
    source: str | None
    score: float | None


class SearchResponse(BaseModel):
    """Search response with results and metadata."""

    results: list[SearchResult]
    total: int
    query: str


class MessageWithContext(BaseModel):
    """Message with surrounding context."""

    message: MessageResponse
    context: list[MessageResponse]
