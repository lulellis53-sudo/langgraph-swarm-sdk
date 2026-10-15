"""FastAPI surface over the swarm SDK."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import orjson
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import RunResult, SwarmSDK
from swarm_sdk.execution import install_uvloop
from swarm_sdk.vault import prime_runtime_secrets

if TYPE_CHECKING:
    app: FastAPI


class RunIn(BaseModel):
    """Request body for ``POST /v1/runs``."""

    text: str = Field(min_length=1)
    thread_id: str = "default"


class RecallIn(BaseModel):
    """Request body for ``POST /v1/recall``."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=50)


def create_app(sdk: SwarmSDK | None = None) -> FastAPI:
    """Build the FastAPI app around ``sdk`` (default: built from settings)."""
    application = FastAPI(title="LangGraph Swarm SDK")
    application.state.sdk = sdk if sdk is not None else SwarmSDK.from_settings()
    application.state.sentry_hook_seen = {}

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness probe: never touches providers."""
        return {"status": "ok"}

    @application.get("/v1/health")
    async def health(request: Request) -> dict[str, object]:
        """Readiness probe with per-provider breaker state."""
        sdk_obj: SwarmSDK = request.app.state.sdk
        return {"status": "ok", "providers": sdk_obj.provider_health()}

    @application.post("/v1/runs", response_model=RunResult)
    async def runs(body: RunIn, request: Request) -> RunResult:
        """Run one swarm turn; handoff loops map to HTTP 508."""
        sdk_obj: SwarmSDK = request.app.state.sdk
        try:
            return await sdk_obj.run(body.text, body.thread_id)
        except GraphRecursionError as err:
            raise HTTPException(
                status_code=508, detail="handoff loop: recursion limit reached"
            ) from err

    @application.post("/v1/recall")
    async def recall(body: RecallIn, request: Request) -> Response:
        """Hybrid-retrieval memory hits as JSON."""
        sdk_obj: SwarmSDK = request.app.state.sdk
        hits = sdk_obj.recall(body.query, body.top_k)
        payload = {"hits": [hit.model_dump() for hit in hits]}
        return Response(content=orjson.dumps(payload), media_type="application/json")

    @application.post("/hooks/sentry", status_code=202)
    async def sentry_hook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
        """Accept signed Sentry event hooks and queue a minimized Watchtower task."""
        from swarm_sdk.observability.sentry import load_sentry_config
        from swarm_sdk.serving.sentry_webhook import (
            dispatch_watchtower,
            event_type,
            summarize_event,
            verify_signature,
        )

        config = load_sentry_config()
        hook_config = config.watchtower if config is not None else None
        if hook_config is None or not hook_config.enabled:
            raise HTTPException(status_code=404, detail="Sentry Watchtower hook is disabled")

        length = request.headers.get("content-length")
        if length is not None:
            try:
                declared_length = int(length)
            except ValueError as error:
                raise HTTPException(status_code=400, detail="Invalid Content-Length") from error
            if declared_length < 0:
                raise HTTPException(status_code=400, detail="Invalid Content-Length")
            if declared_length > hook_config.max_body_bytes:
                raise HTTPException(status_code=413, detail="Sentry hook payload is too large")
        body_buffer = bytearray()
        body_size = 0
        async for chunk in request.stream():
            body_size += len(chunk)
            if body_size > hook_config.max_body_bytes:
                raise HTTPException(status_code=413, detail="Sentry hook payload is too large")
            body_buffer.extend(chunk)
        body = bytes(body_buffer)

        secret = os.environ.get(hook_config.webhook_secret_env, "")
        if not secret:
            raise HTTPException(status_code=503, detail="Sentry hook secret is not configured")
        signature = request.headers.get("sentry-hook-signature", "")
        if not verify_signature(body, signature, secret):
            raise HTTPException(status_code=401, detail="Invalid Sentry hook signature")

        kind = event_type(
            request.headers.get("sentry-hook-resource", ""),
            request.headers.get("sentry-hook-event", ""),
        )
        if kind is None:
            raise HTTPException(status_code=400, detail="Unsupported Sentry hook event headers")
        if kind not in hook_config.allowed_events:
            return {"status": "ignored"}

        try:
            payload = orjson.loads(body)
        except orjson.JSONDecodeError as error:
            raise HTTPException(
                status_code=400, detail="Sentry hook body is not valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Sentry hook body must be a JSON object")
        try:
            event_id, summary = summarize_event(payload, kind)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        dedupe_key = f"{kind}:{event_id}"
        seen: dict[str, None] = application.state.sentry_hook_seen
        if dedupe_key in seen:
            return {"status": "duplicate"}
        seen[dedupe_key] = None
        if len(seen) > 2048:
            seen.pop(next(iter(seen)))

        background_tasks.add_task(
            dispatch_watchtower,
            application.state.sdk,
            summary,
            f"watchtower:{dedupe_key}",
        )
        return {"status": "accepted"}

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
    """Serve the app with uvicorn (uvloop installed, secrets primed)."""
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
