"""Scripted LangChain chat model for WebSearch tests (no Agents/benchmark import)."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict


class Script:
    """Ordered list of canned model replies, consumed one per call."""

    def __init__(self, messages: list[AIMessage]) -> None:
        self.messages = messages
        self.cursor = 0
        self.calls = 0
        self.seen: list[str] = []


class ScriptedModel(BaseChatModel):
    """Chat model that replays scripted messages and records prompts."""

    script: Script
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: object, **kwargs: object) -> ScriptedModel:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.script.calls += 1
        last = messages[-1]
        content = getattr(last, "content", "")
        text = content if isinstance(content, str) else str(content)
        self.script.seen.append(text)
        index = min(self.script.cursor, len(self.script.messages) - 1)
        self.script.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.script.messages[index])])


def answer(text: str) -> AIMessage:
    """Wrap ``text`` as an ``AIMessage``."""
    return AIMessage(content=text)
