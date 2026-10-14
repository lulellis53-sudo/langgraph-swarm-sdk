"""HTTP API over the swarm: FastAPI + uvicorn with SSE streaming."""

__lazy_modules__ = ["fastapi"]

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, StreamingResponse
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "api-thread"


class ChatResponse(BaseModel):
    answer: str


def create_app(*, graph: Any | None = None) -> FastAPI:
    """Build the FastAPI application; a swarm graph may be injected for tests."""
    state: dict[str, Any] = {"graph": graph}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state["graph"] is None:
            from langswarm.blueprint import load_blueprint
            from langswarm.config import settings
            from langswarm.swarm import build_from_blueprint

            state["graph"] = build_from_blueprint(load_blueprint(settings.config_path))
        yield
        state["graph"] = None

    app = FastAPI(
        title="Langswarm",
        version="0.3.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        inputs = {"messages": [{"role": "user", "content": request.message}]}
        config = {"configurable": {"thread_id": request.thread_id}}
        result = await asyncio.to_thread(state["graph"].invoke, inputs, config)
        return ChatResponse(answer=result["messages"][-1].content)

    @app.post("/chat/stream")
    async def chat_stream(request: ChatRequest) -> StreamingResponse:
        from langswarm.runner import stream_swarm

        async def events():
            async for delta in stream_swarm(
                state["graph"], request.message, thread_id=request.thread_id
            ):
                yield f"data: {delta}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def main() -> None:
    """Console entry point: serve the swarm over HTTP with uvicorn on uvloop."""
    from langswarm.config import settings
    from langswarm.log import setup_logging
    from langswarm.runtime import install_uvloop

    install_uvloop()
    setup_logging(settings.log_level, json_logs=settings.log_json)

    import uvicorn

    uvicorn.run(
        create_app(),
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # keep loguru in control of all log output
    )


if __name__ == "__main__":
    main()
