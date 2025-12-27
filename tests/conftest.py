from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.append(str(SRC_ROOT))


@pytest.fixture()
def sample_session_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_session.jsonl"


@pytest.fixture()
def sample_session_messages(sample_session_path: Path) -> list[dict]:
    return [
        json.loads(line) for line in sample_session_path.read_text().splitlines() if line.strip()
    ]


@pytest.fixture()
def temp_session_dir(tmp_path: Path, sample_session_path: Path) -> Path:
    session_dir = tmp_path / "session-123"
    session_dir.mkdir()
    (session_dir / "messages.jsonl").write_text(sample_session_path.read_text())
    return session_dir
