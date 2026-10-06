"""FastAPI surface over the swarm SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING

import orjson
from fastapi import FastAPI, HTTPException, Request, Response
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from swarm_sdk.agents.config.settings import Settings
from swarm_sdk.core.swarm import RunResult, SwarmSDK
from swarm_sdk.runtime.executor import install_uvloop
from swarm_sdk.vault import prime_runtime_secrets

if TYPE_CHECKING:
    app: FastAPI


class RunIn(BaseModel):
    text: str = Field(min_length=1)
    thread_id: str = "default"


class RecallIn(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=50)


def create_app(sdk: SwarmSDK | None = None) -> FastAPI:
    application = FastAPI(title="LangGraph Swarm SDK")
    application.state.sdk = sdk if sdk is not None else SwarmSDK.from_settings()

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/v1/health")
    async def health(request: Request) -> dict[str, object]:
        sdk_obj: SwarmSDK = request.app.state.sdk
        return {"status": "ok", "providers": sdk_obj.provider_health()}

    @application.post("/v1/runs", response_model=RunResult)
    async def runs(body: RunIn, request: Request) -> RunResult:
        sdk_obj: SwarmSDK = request.app.state.sdk
        try:
            return await sdk_obj.run(body.text, body.thread_id)
        except GraphRecursionError as err:
            raise HTTPException(
                status_code=508, detail="handoff loop: recursion limit reached"
            ) from err

    @application.post("/v1/recall")
    async def recall(body: RecallIn, request: Request) -> Response:
        sdk_obj: SwarmSDK = request.app.state.sdk
        hits = sdk_obj.recall(body.query, body.top_k)
        payload = {"hits": [hit.model_dump() for hit in hits]}
        return Response(content=orjson.dumps(payload), media_type="application/json")

    return application


def _default_app() -> FastAPI:
    return create_app()


_app: FastAPI | None = None


def __getattr__(name: str) -> object:
    """Build the default app on first access so importing the module stays cheap."""
    if name == "app":
        global _app
        if _app is None:
            _app = _default_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    import uvicorn

    install_uvloop()
    settings = Settings()
    prime_runtime_secrets()
    uvicorn.run(
        "swarm_sdk.serving.http:app",
        host=settings.api_host,
        port=settings.api_port,
        loop="uvloop",
    )


__all__ = ["RecallIn", "RunIn", "app", "create_app", "main"]
