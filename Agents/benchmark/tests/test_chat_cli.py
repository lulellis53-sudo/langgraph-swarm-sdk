"""Interactive chat and single-route model override behavior."""

from __future__ import annotations

from types import SimpleNamespace

from swarm_sdk.chat_cli import chat_loop
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.graph_builder import GraphBuilder
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.prompting.budget import PackedPrompt


async def test_chat_loop_reuses_thread_and_stops_on_exit() -> None:
    class FakeSDK:
        calls: list[tuple[str, str]]

        def __init__(self) -> None:
            self.calls = []

        async def run(self, text: str, thread_id: str) -> SimpleNamespace:
            self.calls.append((text, thread_id))
            return SimpleNamespace(text=f"answer: {text}")

    sdk = FakeSDK()
    inputs = iter([" hello ", "quit"])
    outputs: list[str] = []

    result = await chat_loop(
        sdk,
        thread_id="thread-7",
        input_fn=lambda _prompt: next(inputs),
        output_fn=outputs.append,
    )

    assert result == 0
    assert sdk.calls == [("hello", "thread-7")]
    assert "answer: hello" in outputs[-1]


def test_global_model_override_applies_to_all_model_loading(monkeypatch) -> None:
    import swarm_sdk.core.graph_builder as graph_builder
    import swarm_sdk.core.swarm as swarm

    loaded: list[str] = []
    model = object()
    monkeypatch.setattr(graph_builder, "load_chat_model", lambda name: loaded.append(name) or model)
    monkeypatch.setattr(swarm, "load_chat_model", lambda name: loaded.append(name) or model)
    settings = Settings(model="openai:gpt-4o-mini")

    graph_sdk = SimpleNamespace(
        settings=settings,
        _specialist_model=None,
        _langgraph_manifests={"worker": object()},
    )
    assert GraphBuilder(graph_sdk).model_for_node("worker") is model

    sdk = object.__new__(SwarmSDK)
    sdk.settings = settings
    sdk._router_model = None
    sdk._specialist_model = None
    assert sdk._router_model_loader() is model
    assert sdk._specialist() is model
    assert loaded == ["openai:gpt-4o-mini"] * 3


async def test_router_uses_global_model_when_structured_output_is_disabled(monkeypatch) -> None:
    import swarm_sdk.core.routing as routing

    model = object()
    calls: list[object] = []

    async def complete(model_arg, *_args, **_kwargs):
        calls.append(model_arg)
        return '{"mode":"parallel","tasks":["one"]}', 3

    async def inline(function, *args, **kwargs):
        return await function(*args, **kwargs)

    monkeypatch.setattr(routing, "complete_with_usage", complete)
    monkeypatch.setattr(routing, "offload", inline)
    sdk = SimpleNamespace(
        settings=SimpleNamespace(model="openai:gpt-4o-mini", router_structured_output=False),
        _router_model=None,
        _router_model_loader=lambda: model,
        _fallback=SimpleNamespace(complete_with_usage=lambda *_args, **_kwargs: None),
        file_config=SimpleNamespace(router=SimpleNamespace(think_level="low")),
    )

    decision, tokens = await routing.Router(sdk).route(PackedPrompt("system", "question"))

    assert calls == [model]
    assert decision.mode == "parallel"
    assert decision.tasks == ["one"]
    assert tokens == 3
