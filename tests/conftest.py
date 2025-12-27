# ABOUTME: Pytest configuration and shared fixtures.
# ABOUTME: Provides sample sessions, search index, and test client fixtures.

import json
from pathlib import Path

import pytest

from claude_code_search.index import SearchIndex

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_messages() -> list[dict]:
    """Load sample session messages from fixture file."""
    messages = []
    fixture_path = FIXTURES_DIR / "sample_session.jsonl"
    with fixture_path.open() as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))
    return messages


@pytest.fixture
def search_index() -> SearchIndex:
    """Create an in-memory search index."""
    return SearchIndex(":memory:")


@pytest.fixture
def indexed_search(search_index: SearchIndex, sample_messages: list[dict]) -> SearchIndex:
    """Create a search index with sample data indexed."""
    search_index.index_session(
        session_id="test-session-001",
        messages=sample_messages,
        source="local",
        project_directory="test-project",
    )
    return search_index
