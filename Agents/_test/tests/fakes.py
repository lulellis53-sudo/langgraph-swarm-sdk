"""Scripted chat models and SDK builders shared by the unit tests."""

from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


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
    return AIMessage(content=text)


def structured(tool_name: str, args: dict[str, Any], total: int | None = None) -> AIMessage:
    """AIMessage whose tool_call args satisfy a ``with_structured_output`` schema.

    The base ``with_structured_output`` binds the schema as a tool and parses
    the reply's first tool call, so a scripted reply carries the schema name
    and its validated fields as ``args``.
    """
    meta = (
        None
        if total is None
        else {"input_tokens": 1, "output_tokens": total - 1, "total_tokens": total}
    )
    return AIMessage(
        content="",
        tool_calls=[
            {"name": tool_name, "args": args, "id": f"call-{tool_name}", "type": "tool_call"}
        ],
        usage_metadata=meta,
    )


def handoff(agent_name: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": f"transfer_to_{agent_name}",
                "args": {},
                "id": f"call-{agent_name}",
                "type": "tool_call",
            }
        ],
    )


ROUTER_OUTPUTS: list[tuple[str, str, list[str]]] = [
    ('{"mode":"parallel","tasks":["a","b"]}', "parallel", ["a", "b"]),
    ('Sure! Here you go: {"mode":"parallel","tasks":["a"]} hope that helps', "parallel", ["a"]),
    ('```json\n{"mode":"swarm","tasks":[]}\n```', "swarm", []),
    ('{"mode":"parallel","tasks":["a"', "swarm", []),
    ("", "swarm", []),
    ("no json at all", "swarm", []),
    ('{"mode":"banana","tasks":[]}', "swarm", []),
    ('{"mode":"parallel","tasks":"not-a-list"}', "swarm", []),
]


def sdk_with_router(
    tmp_path: Path,
    raw: str,
    *,
    structured: bool = True,
    router: ScriptedModel | None = None,
) -> SwarmSDK:
    """Build a SwarmSDK whose router model replies with ``raw`` (or uses ``router``)."""
    model = router or ScriptedModel(script=Script([answer(raw)]))
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
        memory_backend="opencl",
        router_structured_output=structured,
    )
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )
