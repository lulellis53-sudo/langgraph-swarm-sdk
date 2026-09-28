"""Chat-model helpers."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from swarm_sdk.decorators import Static, wrapper
from swarm_sdk.runtime import offload


class ModelProviders:
    """Load LangChain chat models and run bounded completions."""

    @Static
    @wrapper
    def message_text(message: object) -> str:
        """Extract plain text from a LangChain or dict message.

        Args:
            message: Chat message object or role/content dict.

        Returns:
            Concatenated text content.
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

    @Static
    def load_chat_model(model_name: str) -> BaseChatModel:
        """Initialize a chat model by provider string (e.g. ``openai:gpt-4o-mini``).

        Args:
            model_name: LangChain model identifier.

        Returns:
            Chat model instance.

        Raises:
            TypeError: If init does not return ``BaseChatModel``.
        """
        model = init_chat_model(model_name)
        if not isinstance(model, BaseChatModel):
            raise TypeError(f"expected a chat model, got {type(model).__name__}")
        return model

    @Static
    async def complete(model: BaseChatModel, system: str, user: str) -> str:
        """One system + user turn, offloaded from the event loop.

        Args:
            model: Chat model to invoke.
            system: System prompt.
            user: User message.

        Returns:
            Assistant text from the model response.
        """

        def _call() -> str:
            result = model.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)],
            )
            return ModelProviders.message_text(result)

        return await offload(_call)

    @Static
    @wrapper
    def last_ai_text(messages: list[object]) -> str:
        """Return the latest assistant message text from a transcript.

        Args:
            messages: Conversation messages (newest may be last).

        Returns:
            Last non-empty AI/assistant content, or last message fallback.
        """
        for message in reversed(messages):
            if isinstance(message, dict):
                kind = message.get("role") or message.get("type")
            else:
                kind = getattr(message, "type", None)
            if kind in {"ai", "assistant"}:
                text = ModelProviders.message_text(message)
                if text:
                    return text
        if not messages:
            return ""
        return ModelProviders.message_text(messages[-1])


def message_text(message: object) -> str:
    """See :meth:`ModelProviders.message_text`."""
    return ModelProviders.message_text(message)


def load_chat_model(model_name: str) -> BaseChatModel:
    """See :meth:`ModelProviders.load_chat_model`."""
    return ModelProviders.load_chat_model(model_name)


async def complete(model: BaseChatModel, system: str, user: str) -> str:
    """See :meth:`ModelProviders.complete`."""
    return await ModelProviders.complete(model, system, user)


def last_ai_text(messages: list[object]) -> str:
    """See :meth:`ModelProviders.last_ai_text`."""
    return ModelProviders.last_ai_text(messages)
