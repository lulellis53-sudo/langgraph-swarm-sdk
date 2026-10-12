"""HTTP behaviour of the model gateway router."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

from swarm_sdk.serving.gateway import build_router

TOKEN = "t0k"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"model": "fake:a", "messages": [{"role": "user", "content": "hi"}]}


class StreamFake(BaseChatModel):
    """Streams ``chunks``; raises ``RuntimeError`` when the index reaches ``error_at``."""

    chunks: list[AIMessageChunk]
    error_at: int | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "stream-fake"

    def bind_tools(self, tools: object, **kwargs: object) -> StreamFake:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        if self.error_at == 0:
            raise RuntimeError("boom")
        merged = self.chunks[0]
        for chunk in self.chunks[1:]:
            merged = merged + chunk
        message = AIMessage(
            content=merged.content,
            tool_calls=merged.tool_calls,
            usage_metadata=merged.usage_metadata,
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        for index, chunk in enumerate(self.chunks):
            if self.error_at is not None and index >= self.error_at:
                raise RuntimeError("boom")
            yield ChatGenerationChunk(message=chunk)
        if self.error_at is not None and self.error_at >= len(self.chunks):
            raise RuntimeError("boom")


def make_client(models: dict[str, StreamFake], token: str | None = TOKEN) -> TestClient:
    router = build_router(
        token=lambda: token,
        loader=lambda name: models[name],
        routes=lambda: tuple(models),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def text_model(text: str = "hello") -> StreamFake:
    return StreamFake(chunks=[AIMessageChunk(content=text)])


def test_missing_token_is_401() -> None:
    client = make_client({"fake:a": text_model()})
    assert client.post("/v1/chat/completions", json=BODY).status_code == 401


def test_wrong_token_is_401() -> None:
    client = make_client({"fake:a": text_model()})
    response = client.post(
        "/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401


def test_unconfigured_token_fails_closed_with_503() -> None:
    client = make_client({"fake:a": text_model()}, token=None)
    assert client.post("/v1/chat/completions", json=BODY, headers=AUTH).status_code == 503


def test_unauthenticated_malformed_body_is_401_not_422() -> None:
    client = make_client({"fake:a": text_model()})
    assert client.post("/v1/chat/completions", json={"nope": 1}).status_code == 401


def test_models_lists_routes() -> None:
    client = make_client({"fake:a": text_model(), "fake:b": text_model()})
    response = client.get("/v1/models", headers=AUTH)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == ["fake:a", "fake:b"]


def test_unknown_route_is_404() -> None:
    client = make_client({"fake:a": text_model()})
    body = {**BODY, "model": "fake:missing"}
    assert client.post("/v1/chat/completions", json=body, headers=AUTH).status_code == 404


def test_bad_role_is_422() -> None:
    client = make_client({"fake:a": text_model()})
    body = {**BODY, "messages": [{"role": "narrator", "content": "x"}]}
    assert client.post("/v1/chat/completions", json=body, headers=AUTH).status_code == 422


def test_non_streaming_text_completion() -> None:
    client = make_client({"fake:a": text_model("hello")})
    response = client.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "hello"}
    assert choice["finish_reason"] == "stop"


def test_non_streaming_tool_call() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "ls", "args": '{"path": "."}', "id": "call_1", "index": 0}],
    )
    client = make_client({"fake:a": StreamFake(chunks=[chunk])})
    body = {**BODY, "tools": [{"type": "function", "function": {"name": "ls", "parameters": {}}}]}
    choice = client.post("/v1/chat/completions", json=body, headers=AUTH).json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "ls"


def sse_events(text: str) -> list[Any]:
    events: list[Any] = []
    for line in text.splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            events.append("[DONE]" if payload == "[DONE]" else json.loads(payload))
    return events


def stream_body(**extra: object) -> dict[str, object]:
    return {**BODY, "stream": True, **extra}


def test_stream_order_role_content_usage_done() -> None:
    model = StreamFake(
        chunks=[
            AIMessageChunk(content="he"),
            AIMessageChunk(
                content="llo",
                response_metadata={"finish_reason": "stop"},
                usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            ),
        ]
    )
    client = make_client({"fake:a": model})
    response = client.post("/v1/chat/completions", json=stream_body(), headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    assert events[-1] == "[DONE]"
    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(
        event["choices"][0]["delta"].get("content", "")
        for event in events[:-2]
        if isinstance(event, dict) and event["choices"]
    )
    assert text == "hello"
    assert events[-2]["choices"] == []
    assert events[-2]["usage"]["total_tokens"] == 5


def test_stream_preserves_non_ascii() -> None:
    client = make_client({"fake:a": text_model("ação 日本語")})
    response = client.post("/v1/chat/completions", json=stream_body(), headers=AUTH)
    deltas = [
        event["choices"][0]["delta"].get("content", "")
        for event in sse_events(response.text)
        if isinstance(event, dict) and event["choices"]
    ]
    assert "ação 日本語" in "".join(deltas)


def test_stream_tool_call_deltas() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "ls", "args": '{"path": "."}', "id": "call_1", "index": 0}],
    )
    client = make_client({"fake:a": StreamFake(chunks=[chunk])})
    body = stream_body(tools=[{"type": "function", "function": {"name": "ls", "parameters": {}}}])
    events = sse_events(client.post("/v1/chat/completions", json=body, headers=AUTH).text)
    calls = [
        event["choices"][0]["delta"]["tool_calls"][0]
        for event in events
        if isinstance(event, dict)
        and event["choices"]
        and "tool_calls" in event["choices"][0]["delta"]
    ]
    assert calls[0]["id"] == "call_1"
    assert calls[0]["function"]["name"] == "ls"


def test_mid_stream_failure_emits_error_event_then_done() -> None:
    model = StreamFake(
        chunks=[AIMessageChunk(content="a"), AIMessageChunk(content="b")], error_at=1
    )
    client = make_client({"fake:a": model})
    events = sse_events(client.post("/v1/chat/completions", json=stream_body(), headers=AUTH).text)
    assert events[-1] == "[DONE]"
    assert events[-2]["error"]["type"] == "upstream_error"


def test_fallback_serves_second_route_when_first_fails_before_first_chunk() -> None:
    models = {
        "fake:a": StreamFake(chunks=[], error_at=0),
        "fake:b": text_model("from b"),
    }
    client = make_client(models)
    body = stream_body(x_fallback_models=["fake:b"])
    events = sse_events(client.post("/v1/chat/completions", json=body, headers=AUTH).text)
    assert events[0]["model"] == "fake:b"
    assert "from b" in json.dumps(events)


def test_all_routes_failing_is_503_with_attempt_count() -> None:
    models = {
        "fake:a": StreamFake(chunks=[], error_at=0),
        "fake:b": StreamFake(chunks=[], error_at=0),
    }
    client = make_client(models)
    body = stream_body(x_fallback_models=["fake:b"])
    response = client.post("/v1/chat/completions", json=body, headers=AUTH)
    assert response.status_code == 503
    assert "2 attempt(s)" in response.json()["detail"]


def test_non_streaming_fallback() -> None:
    models = {
        "fake:a": StreamFake(chunks=[], error_at=0),
        "fake:b": text_model("from b"),
    }
    client = make_client(models)
    body = {**BODY, "x_fallback_models": ["fake:b"]}
    reply = client.post("/v1/chat/completions", json=body, headers=AUTH).json()
    assert reply["model"] == "fake:b"
    assert reply["choices"][0]["message"]["content"] == "from b"
