from __future__ import annotations

from pathlib import Path

from claude_code_search.loaders.local import discover_local_sessions, load_local_session


def test_discover_local_sessions(temp_session_dir: Path) -> None:
    sessions = discover_local_sessions(root_dir=temp_session_dir.parent)
    assert sessions
    assert sessions[0]["id"] == temp_session_dir.name


def test_load_local_session(temp_session_dir: Path) -> None:
    messages = load_local_session(temp_session_dir.name, root_dir=temp_session_dir.parent)
    assert len(messages) == 3
    assert messages[0]["uuid"] == "msg-001"


def test_discover_local_sessions_uses_env_dir(
    tmp_path: Path, sample_session_path: Path, monkeypatch
) -> None:
    session_dir = tmp_path / "session-env"
    session_dir.mkdir()
    (session_dir / "messages.jsonl").write_text(sample_session_path.read_text())

    monkeypatch.setenv("CLAUDE_CODE_SESSIONS_DIR", str(tmp_path))

    sessions = discover_local_sessions()
    assert sessions
    assert sessions[0]["id"] == "session-env"


def test_discover_local_sessions_from_projects_dir(
    tmp_path: Path, sample_session_path: Path, monkeypatch
) -> None:
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "encoded-project"
    project_dir.mkdir(parents=True)
    session_file = project_dir / "session-001.jsonl"
    session_file.write_text(sample_session_path.read_text())

    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(projects_dir))
    monkeypatch.setenv("CLAUDE_CODE_SESSIONS_DIR", str(tmp_path / "empty"))

    sessions = discover_local_sessions()
    assert sessions
    assert sessions[0]["path"] == str(session_file)
    assert sessions[0]["project_directory"] == str(project_dir)
