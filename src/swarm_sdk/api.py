"""FastAPI surface over the swarm SDK."""

import orjson
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

from swarm_sdk.config import Settings
from swarm_sdk.runtime import install_uvloop
from swarm_sdk.swarm import RunResult, SwarmSDK


class RunIn(BaseModel):
    text: str = Field(min_length=1)
    thread_id: str = "default"


class RecallIn(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=50)


def create_app(sdk: SwarmSDK | None = None) -> FastAPI:
    application = FastAPI(title="LangGraph Swarm SDK")
    application.state.sdk = sdk if sdk is not None else SwarmSDK.from_settings()

    @application.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/v1/runs", response_model=RunResult)
    async def runs(body: RunIn, request: Request) -> RunResult:
        sdk_obj: SwarmSDK = request.app.state.sdk
        return await sdk_obj.run(body.text, body.thread_id)

    @application.post("/v1/recall")
    async def recall(body: RecallIn, request: Request) -> Response:
        sdk_obj: SwarmSDK = request.app.state.sdk
        hits = sdk_obj.recall(body.query, body.top_k)
        payload = {"hits": [hit.model_dump() for hit in hits]}
        return Response(content=orjson.dumps(payload), media_type="application/json")

    return application


app = create_app()


def main() -> None:
    import uvicorn

    install_uvloop()
    settings = Settings()
    uvicorn.run(
        "swarm_sdk.api:app",
        host=settings.api_host,
        port=settings.api_port,
        loop="uvloop",
    )
