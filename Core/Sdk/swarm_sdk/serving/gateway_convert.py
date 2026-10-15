"""OpenAI chat-completions JSON <-> LangChain messages, for the model gateway."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage


class GatewayRequestError(ValueError):
    """The request body is well-formed JSON but not a valid chat-completions payload."""


def _text(content: object) -> str:
    """Return message text from a string, a list of text parts, or ``None``."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    raise GatewayRequestError("message content must be a string or a list of text parts")


def _tool_calls(raw: object) -> list[dict[str, Any]]:
    """Convert OpenAI ``tool_calls`` into LangChain tool-call dicts."""
    calls: list[dict[str, Any]] = []
    for item in raw or []:
        try:
            function = item["function"]
            arguments = function.get("arguments") or "{}"
            args = json.loads(arguments)
            calls.append({"id": item["id"], "name": function["name"], "args": args})
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as err:
            raise GatewayRequestError("invalid assistant tool_calls entry") from err
    return calls


def to_langchain_messages(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert OpenAI request messages to LangChain messages.

    Args:
        messages: The ``messages`` array of a chat-completions request.

    Returns:
        LangChain messages in the same order.

    Raises:
        GatewayRequestError: On an unknown role, bad content, or bad tool call.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    converted: list[BaseMessage] = []
    for message in messages:
        role = message.get("role")
        text = _text(message.get("content"))
        if role == "system":
            converted.append(SystemMessage(content=text))
        elif role == "user":
            converted.append(HumanMessage(content=text))
        elif role == "assistant":
            converted.append(
                AIMessage(content=text, tool_calls=_tool_calls(message.get("tool_calls")))
            )
        elif role == "tool":
            try:
                converted.append(ToolMessage(content=text, tool_call_id=message["tool_call_id"]))
            except KeyError as err:
                raise GatewayRequestError("tool message needs tool_call_id") from err
        else:
            raise GatewayRequestError(f"unsupported role: {role!r}")
    return converted


_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "content_filter"})


def _finish_reason(metadata: dict[str, Any]) -> str | None:
    """Return a normalised OpenAI finish reason, or ``None`` while still streaming."""
    reason = metadata.get("finish_reason")
    if reason is None:
        return None
    return reason if reason in _FINISH_REASONS else "stop"


def _envelope(
    obj: str, completion_id: str, model: str, created: int, choices: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": obj,
        "created": created,
        "model": model,
        "choices": choices,
    }


def _usage(usage: dict[str, int]) -> dict[str, int]:
    return {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def role_chunk(*, completion_id: str, model: str, created: int) -> dict[str, Any]:
    """Return the opening stream event that announces the assistant role."""
    delta = {"role": "assistant", "content": ""}
    choice = {"index": 0, "delta": delta, "finish_reason": None}
    return _envelope("chat.completion.chunk", completion_id, model, created, [choice])


def chunk_to_openai(
    chunk: AIMessageChunk, *, completion_id: str, model: str, created: int
) -> dict[str, Any]:
    """Convert one LangChain stream chunk to an OpenAI ``chat.completion.chunk``."""
    delta: dict[str, Any] = {}
    text = _text(chunk.content)
    if text:
        delta["content"] = text
    if chunk.tool_call_chunks:
        delta["tool_calls"] = [
            {
                "index": call.get("index") or 0,
                **({"id": call["id"]} if call.get("id") else {}),
                "type": "function",
                "function": {
                    **({"name": call["name"]} if call.get("name") else {}),
                    "arguments": call.get("args") or "",
                },
            }
            for call in chunk.tool_call_chunks
        ]
    choice = {
        "index": 0,
        "delta": delta,
        "finish_reason": _finish_reason(chunk.response_metadata),
    }
    return _envelope("chat.completion.chunk", completion_id, model, created, [choice])


def usage_chunk(
    usage: dict[str, int], *, completion_id: str, model: str, created: int
) -> dict[str, Any]:
    """Return the final stream event that carries token usage and no choices."""
    event = _envelope("chat.completion.chunk", completion_id, model, created, [])
    event["usage"] = _usage(usage)
    return event


def message_to_openai(
    message: AIMessage, *, completion_id: str, model: str, created: int
) -> dict[str, Any]:
    """Convert a complete LangChain reply to an OpenAI ``chat.completion`` body."""
    out: dict[str, Any] = {"role": "assistant", "content": _text(message.content)}
    finish = _finish_reason(message.response_metadata) or "stop"
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
            }
            for call in message.tool_calls
        ]
        finish = "tool_calls"
    body = _envelope(
        "chat.completion",
        completion_id,
        model,
        created,
        [{"index": 0, "message": out, "finish_reason": finish}],
    )
    if message.usage_metadata:
        body["usage"] = _usage(dict(message.usage_metadata))
    return body
