"""Conversion between OpenAI chat-completions JSON and LangChain messages."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from swarm_sdk.serving.gateway_convert import GatewayRequestError, to_langchain_messages


def test_roles_map_to_langchain_types() -> None:
    messages = to_langchain_messages(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "ls", "arguments": '{"path": "."}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "a.txt"},
        ]
    )
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert isinstance(messages[2], AIMessage)
    assert messages[2].tool_calls == [
        {"id": "call_1", "name": "ls", "args": {"path": "."}, "type": "tool_call"}
    ]
    assert isinstance(messages[3], ToolMessage)
    assert messages[3].tool_call_id == "call_1"


def test_content_parts_are_joined() -> None:
    messages = to_langchain_messages(
        [
            {
                "role": "user",
                "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
            }
        ]
    )
    assert messages[0].content == "ab"


def test_invalid_tool_arguments_json_raises() -> None:
    with pytest.raises(GatewayRequestError):
        to_langchain_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c",
                            "type": "function",
                            "function": {"name": "ls", "arguments": "{oops"},
                        }
                    ],
                }
            ]
        )


def test_unknown_role_raises() -> None:
    with pytest.raises(GatewayRequestError):
        to_langchain_messages([{"role": "narrator", "content": "x"}])


def test_empty_arguments_become_empty_dict() -> None:
    messages = to_langchain_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c", "type": "function", "function": {"name": "now", "arguments": ""}}
                ],
            }
        ]
    )
    assert messages[0].tool_calls[0]["args"] == {}
