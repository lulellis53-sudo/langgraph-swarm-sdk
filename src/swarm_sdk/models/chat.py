"""Chat-model helpers."""

from __future__ import annotations

import logging

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from swarm_sdk.execution.executor import offload
from swarm_sdk.prompting.budget import count_text

logger = logging.getLogger(__name__)


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


def message_tokens(message: object) -> int | None:
    """Return the provider-reported token total for one message, if any."""
    if isinstance(message, dict):
        meta = message.get("usage_metadata")
    else:
        meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    total = meta.get("total_tokens")
    if isinstance(total, int):
        return total
    prompt, reply = meta.get("input_tokens"), meta.get("output_tokens")
    if isinstance(prompt, int) and isinstance(reply, int):
        return prompt + reply
    return None


def _message_kind(message: object) -> object:
    if isinstance(message, dict):
        return message.get("role") or message.get("type")
    return getattr(message, "type", None)


def usage_tokens(messages: list[object]) -> int | None:
    """Sum provider token totals for AI messages after the last human message.

    Earlier turns are replayed by the checkpointer; counting them would double-charge.
    Returns ``None`` when no message reports usage.
    """
    start = 0
    for index, message in enumerate(messages):
        if _message_kind(message) in {"human", "user"}:
            start = index + 1
    reported = [t for m in messages[start:] if (t := message_tokens(m)) is not None]
    return sum(reported) if reported else None


async def complete_with_usage(
    model: BaseChatModel,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
) -> tuple[str, int]:
    """Invoke ``model`` on a system+user pair and return ``(text, tokens)``.

    Args:
        model: Chat model to call.
        system: System prompt.
        user: User / packed prompt body.
        json_mode: Ask the provider for a JSON object; retried once without it if the
            provider rejects ``response_format``.

    Returns:
        The reply text and the provider-reported token total, or an estimate
        (``count_text`` of system, user and reply) when the provider reports none.
    """

    def _call() -> tuple[str, int]:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        result = None
        if json_mode:
            try:
                result = model.bind(response_format={"type": "json_object"}).invoke(messages)
            except Exception:
                logger.warning("provider rejected response_format; retrying without it")
        if result is None:
            result = model.invoke(messages)
        text = message_text(result)
        reported = message_tokens(result)
        if reported is None:
            reported = count_text(system) + count_text(user) + count_text(text)
        return text, reported

    return await offload(_call)


async def complete(model: BaseChatModel, system: str, user: str) -> str:
    """Invoke ``model`` on a system+user pair via the shared thread pool.

    Args:
        model: Chat model to call.
        system: System prompt.
        user: User / packed prompt body.

    Returns:
        Model reply text.
    """
    text, _ = await complete_with_usage(model, system, user)
    return text


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
    "complete_with_usage",
    "last_ai_text",
    "load_chat_model",
    "message_text",
    "message_tokens",
    "usage_tokens",
]
