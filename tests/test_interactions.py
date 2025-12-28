# ABOUTME: Tests for interaction grouping functionality.
# ABOUTME: Verifies grouping of messages into logical user-assistant exchanges.

from claude_code_search.parsers import group_messages_into_interactions


class TestInteractionGrouping:
    """Tests for grouping messages into interactions."""

    def test_simple_user_assistant_exchange(self) -> None:
        """Group a simple user question and assistant response."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Hello"}},
            {"uuid": "msg-2", "message": {"role": "assistant", "content": "Hi there!"}},
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        assert len(interactions) == 1
        interaction = interactions[0]
        assert interaction.interaction_id == "session-1-interaction-0"
        assert interaction.user_prompt == "Hello"
        assert len(interaction.message_ids) == 2
        assert interaction.message_ids == ["msg-1", "msg-2"]
        assert interaction.has_thinking is False
        assert len(interaction.tool_calls) == 0
        assert len(interaction.commits) == 0

    def test_interaction_with_tools(self) -> None:
        """Group interaction with tool usage."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Create a file"}},
            {
                "uuid": "msg-2",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll create it"},
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Write",
                            "input": {"path": "test.py"},
                        },
                    ],
                },
            },
            {
                "uuid": "msg-3",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "Done"}
                    ],
                },
            },
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        assert len(interactions) == 1
        interaction = interactions[0]
        assert len(interaction.message_ids) == 3
        assert len(interaction.tool_calls) == 1
        assert interaction.tool_calls[0] == "Write"

    def test_interaction_with_thinking(self) -> None:
        """Detect interactions with extended thinking."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Solve this"}},
            {
                "uuid": "msg-2",
                "message": {"role": "assistant", "content": "Here's the solution"},
                "thinking": "Let me analyze this problem...",
            },
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        assert len(interactions) == 1
        assert interactions[0].has_thinking is True

    def test_interaction_with_commits(self) -> None:
        """Track commits within an interaction."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Commit changes"}},
            {
                "uuid": "msg-2",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Bash",
                            "input": {"command": "git commit -m 'fix: bug'"},
                        }
                    ],
                },
            },
            {
                "uuid": "msg-3",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": "[main abc1234] fix: bug",
                        }
                    ],
                },
            },
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        assert len(interactions) == 1
        assert len(interactions[0].commits) == 1
        assert interactions[0].commits[0].commit_hash == "abc1234"

    def test_multiple_interactions(self) -> None:
        """Group multiple user-assistant exchanges."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "First question"}},
            {
                "uuid": "msg-2",
                "message": {"role": "assistant", "content": "First answer"},
            },
            {"uuid": "msg-3", "message": {"role": "user", "content": "Second question"}},
            {
                "uuid": "msg-4",
                "message": {"role": "assistant", "content": "Second answer"},
            },
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        assert len(interactions) == 2
        assert interactions[0].user_prompt == "First question"
        assert interactions[1].user_prompt == "Second question"
        assert interactions[0].interaction_id == "session-1-interaction-0"
        assert interactions[1].interaction_id == "session-1-interaction-1"

    def test_interaction_with_multiple_tools(self) -> None:
        """Track multiple tool calls in one interaction."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Setup project"}},
            {
                "uuid": "msg-2",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Write",
                            "input": {"path": "a.py"},
                        },
                        {
                            "type": "tool_use",
                            "id": "tool-2",
                            "name": "Bash",
                            "input": {"command": "npm install"},
                        },
                    ],
                },
            },
            {
                "uuid": "msg-3",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "OK"},
                        {"type": "tool_result", "tool_use_id": "tool-2", "content": "Done"},
                    ],
                },
            },
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        assert len(interactions) == 1
        assert len(interactions[0].tool_calls) == 2
        assert "Write" in interactions[0].tool_calls
        assert "Bash" in interactions[0].tool_calls

    def test_assistant_starts_conversation(self) -> None:
        """Handle edge case where assistant starts (shouldn't happen but handle gracefully)."""
        messages = [
            {
                "uuid": "msg-1",
                "message": {"role": "assistant", "content": "Hello! How can I help?"},
            },
            {"uuid": "msg-2", "message": {"role": "user", "content": "Create a file"}},
            {"uuid": "msg-3", "message": {"role": "assistant", "content": "Done"}},
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        # First assistant message creates a standalone interaction
        assert len(interactions) == 2
        assert interactions[0].user_prompt == ""  # No user prompt
        assert interactions[1].user_prompt == "Create a file"

    def test_user_only_messages(self) -> None:
        """Handle consecutive user messages (tool results)."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Do something"}},
            {
                "uuid": "msg-2",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        }
                    ],
                },
            },
            {
                "uuid": "msg-3",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "file.txt"}
                    ],
                },
            },
            {
                "uuid": "msg-4",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tool-1", "content": "more data"}
                    ],
                },
            },
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        # All messages belong to one interaction
        assert len(interactions) == 1
        assert len(interactions[0].message_ids) == 4

    def test_match_location_tracking(self) -> None:
        """Interaction should track where search matches occurred."""
        messages = [
            {"uuid": "msg-1", "message": {"role": "user", "content": "Hello"}},
            {"uuid": "msg-2", "message": {"role": "assistant", "content": "Hi"}},
        ]

        interactions = group_messages_into_interactions(messages, "session-1")

        # Initially no match locations
        assert interactions[0].match_locations == []

        # Simulate marking a match
        interactions[0].match_locations = [
            {"message_id": "msg-1", "type": "user_prompt"},
            {"message_id": "msg-2", "type": "assistant_response"},
        ]
        assert len(interactions[0].match_locations) == 2
