"""Chat-model helpers."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from swarm_sdk.execution.executor import offload


def message_text(message: object) -> str:
    """Extract plain text from a chat message or dict payload.

    Args:
        message: LangChain message, dict with ``content``, or other object.

    Returns:
        Concatenated text content, or ``str(message)`` as a last resort.
    """
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content)


def load_chat_model(model_name: str) -> BaseChatModel:
    """Initialize a LangChain chat model from a provider:name string.

    Args:
        model_name: e.g. ``"openai:gpt-4o-mini"``.

    Returns:
        A ``BaseChatModel`` instance.

    Raises:
        TypeError: If ``init_chat_model`` does not return a chat model.
    """
    model = init_chat_model(model_name)
    if not isinstance(model, BaseChatModel):
        raise TypeError(f"expected a chat model, got {type(model).__name__}")
    return model


async def complete(model: BaseChatModel, system: str, user: str) -> str:
    """Invoke ``model`` on a system+user pair via the shared thread pool.

    Args:
        model: Chat model to call.
        system: System prompt.
        user: User / packed prompt body.

    Returns:
        Model reply text.
    """

    def _call() -> str:
        result = model.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)],
        )
        return message_text(result)

    return await offload(_call)


def last_ai_text(messages: list[object]) -> str:
    """Return the last assistant/AI message text from a transcript.

    Args:
        messages: Chronological message list (dicts or LangChain messages).

    Returns:
        Last AI/assistant text, or the last message's text, or ``""``.
    """
    for message in reversed(messages):
        if isinstance(message, dict):
            kind = message.get("role") or message.get("type")
        else:
            kind = getattr(message, "type", None)
        if kind in {"ai", "assistant"}:
            text = message_text(message)
            if text:
                return text
    if not messages:
        return ""
    return message_text(messages[-1])


__all__ = [
    "complete",
    "last_ai_text",
    "load_chat_model",
    "message_text",
]
