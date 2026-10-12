"""Conversion between OpenAI chat-completions JSON and LangChain messages."""

from __future__ import annotations

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from swarm_sdk.serving.gateway_convert import (
    GatewayRequestError,
    chunk_to_openai,
    message_to_openai,
    role_chunk,
    to_langchain_messages,
    usage_chunk,
)

META = {"completion_id": "chatcmpl-1", "model": "openai:gpt-4o-mini", "created": 1}


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


def test_role_chunk_opens_the_stream() -> None:
    event = role_chunk(**META)
    assert event["object"] == "chat.completion.chunk"
    assert event["choices"][0]["delta"] == {"role": "assistant", "content": ""}


def test_text_chunk_has_content_delta() -> None:
    event = chunk_to_openai(AIMessageChunk(content="olá"), **META)
    assert event["choices"][0]["delta"] == {"content": "olá"}
    assert event["choices"][0]["finish_reason"] is None


def test_tool_call_chunk_none_index_becomes_zero() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "ls", "args": '{"p"', "id": "call_1", "index": None}],
    )
    delta = chunk_to_openai(chunk, **META)["choices"][0]["delta"]
    assert delta["tool_calls"] == [
        {
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {"name": "ls", "arguments": '{"p"'},
        }
    ]


def test_finish_reason_is_normalised() -> None:
    chunk = AIMessageChunk(content="", response_metadata={"finish_reason": "length"})
    assert chunk_to_openai(chunk, **META)["choices"][0]["finish_reason"] == "length"
    odd = AIMessageChunk(content="", response_metadata={"finish_reason": "weird"})
    assert chunk_to_openai(odd, **META)["choices"][0]["finish_reason"] == "stop"


def test_usage_chunk_shape() -> None:
    event = usage_chunk({"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}, **META)
    assert event["choices"] == []
    assert event["usage"] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}


def test_message_with_tool_calls_serialises_arguments() -> None:
    message = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "ls", "args": {"path": "."}}],
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )
    body = message_to_openai(message, **META)
    choice = body["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["id"] == "call_1"
    assert call["function"] == {"name": "ls", "arguments": '{"path": "."}'}
    assert body["usage"]["total_tokens"] == 3


def test_plain_message_finishes_with_stop() -> None:
    body = message_to_openai(AIMessage(content="hi"), **META)
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "hi"}
    assert body["choices"][0]["finish_reason"] == "stop"
    assert "usage" not in body
