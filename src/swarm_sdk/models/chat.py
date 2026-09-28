"""Chat-model helpers."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from swarm_sdk.execution.executor import offload


def message_text(message: object) -> str:
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
    model = init_chat_model(model_name)
    if not isinstance(model, BaseChatModel):
        raise TypeError(f"expected a chat model, got {type(model).__name__}")
    return model


async def complete(model: BaseChatModel, system: str, user: str) -> str:
    def _call() -> str:
        result = model.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)],
        )
        return message_text(result)

    return await offload(_call)


def last_ai_text(messages: list[object]) -> str:
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
