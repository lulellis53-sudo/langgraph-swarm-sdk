"""OpenAI chat-completions JSON <-> LangChain messages, for the model gateway."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


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
