"""FastAPI endpoint tests using an injected graph and no model calls."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from langswarm.api import create_app


class FakeGraph:
    def invoke(self, inputs, config=None):
        return {"messages": [SimpleNamespace(content="all good")]}

    async def astream(self, inputs, config=None, stream_mode="messages"):
        yield SimpleNamespace(content="hello "), {}


def test_health_and_chat() -> None:
    with TestClient(create_app(graph=FakeGraph())) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        reply = client.post("/chat", json={"message": "hi"})
        assert reply.json()["answer"] == "all good"


def test_stream_emits_sse_events() -> None:
    with TestClient(create_app(graph=FakeGraph())) as client:
        response = client.post("/chat/stream", json={"message": "hi"})
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "hello" in response.text
        assert "[DONE]" in response.text
