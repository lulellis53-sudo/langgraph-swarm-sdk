"""OpenAI-compatible chat-completions gateway over the swarm model routes."""

from __future__ import annotations

import hmac
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from swarm_sdk import vault
from swarm_sdk.models import chat as chat_models
from swarm_sdk.serving.gateway_convert import (
    GatewayRequestError,
    chunk_to_openai,
    message_to_openai,
    role_chunk,
    to_langchain_messages,
    usage_chunk,
)

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk, BaseMessage

logger = logging.getLogger(__name__)

TOKEN_ENV = "SWARM_GATEWAY_TOKEN"


class ChatCompletionIn(BaseModel):
    """Request body for ``POST /v1/chat/completions``."""

    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    x_fallback_models: list[str] = Field(default_factory=list)


def _default_token() -> str | None:
    return vault.get(TOKEN_ENV)


def _bind(model: BaseChatModel, body: ChatCompletionIn) -> Any:
    """Apply tools and sampling options to ``model``."""
    bound: Any = model
    if body.tools:
        extra = {"tool_choice": body.tool_choice} if body.tool_choice is not None else {}
        bound = bound.bind_tools(body.tools, **extra)
    options = {
        key: value
        for key, value in (("temperature", body.temperature), ("max_tokens", body.max_tokens))
        if value is not None
    }
    return bound.bind(**options) if options else bound


def build_router(
    *,
    token: Callable[[], str | None] = _default_token,
    loader: Callable[[str], BaseChatModel] = chat_models.load_chat_model,
    routes: Callable[[], tuple[str, ...]] = chat_models.known_routes,
) -> APIRouter:
    """Build the gateway router.

    Args:
        token: Returns the expected bearer token, or ``None`` when unconfigured.
        loader: Returns the chat model for a route name.
        routes: Returns every route name the gateway may serve.
    """
    router = APIRouter()

    def authorize(request: Request) -> None:
        expected = token()
        if not expected:
            raise HTTPException(status_code=503, detail="gateway token not configured")
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.encode(), expected.encode()
        ):
            raise HTTPException(status_code=401, detail="invalid bearer token")

    @router.get("/v1/models", dependencies=[Depends(authorize)])
    async def list_models() -> dict[str, Any]:
        data = [{"id": name, "object": "model", "owned_by": "swarm"} for name in routes()]
        return {"object": "list", "data": data}

    @router.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    async def completions(body: ChatCompletionIn) -> Any:
        names = [body.model, *body.x_fallback_models]
        known = set(routes())
        for name in names:
            if name not in known:
                raise HTTPException(status_code=404, detail=f"unknown route: {name}")
        try:
            messages = to_langchain_messages(body.messages)
        except GatewayRequestError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        meta = {
            "completion_id": f"chatcmpl-{uuid.uuid4().hex}",
            "created": int(time.time()),
        }
        if body.stream:
            name, first, rest = await _open_stream(names, messages, body, loader)
            return StreamingResponse(_sse(name, first, rest, meta), media_type="text/event-stream")
        return await _complete(names, messages, body, loader, meta)

    return router


async def _complete(
    names: list[str],
    messages: list[BaseMessage],
    body: ChatCompletionIn,
    loader: Callable[[str], BaseChatModel],
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Return the first successful non-streaming reply across ``names``."""
    for name in names:
        try:
            reply = await _bind(loader(name), body).ainvoke(messages)
        except Exception as err:
            logger.warning("gateway route %s failed: %s", name, type(err).__name__)
            continue
        return message_to_openai(reply, model=name, **meta)
    raise HTTPException(status_code=503, detail=f"all routes failed after {len(names)} attempt(s)")


async def _open_stream(
    names: list[str],
    messages: list[BaseMessage],
    body: ChatCompletionIn,
    loader: Callable[[str], BaseChatModel],
) -> tuple[str, AIMessageChunk | None, AsyncIterator[AIMessageChunk]]:
    """Pick the first route that yields a first chunk; 503 when none does."""
    for name in names:
        try:
            iterator = _bind(loader(name), body).astream(messages).__aiter__()
            first = await anext(iterator, None)
        except Exception as err:
            logger.warning(
                "gateway route %s failed before first chunk: %s", name, type(err).__name__
            )
            continue
        return name, first, iterator
    raise HTTPException(status_code=503, detail=f"all routes failed after {len(names)} attempt(s)")


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _sse(
    name: str,
    first: AIMessageChunk | None,
    rest: AsyncIterator[AIMessageChunk],
    meta: dict[str, Any],
) -> AsyncIterator[str]:
    """Yield OpenAI stream events; the last usage-bearing chunk wins."""
    usage: dict[str, int] | None = None
    yield _event(role_chunk(model=name, **meta))
    try:
        pending = [first] if first is not None else []
        for chunk in pending:
            usage = dict(chunk.usage_metadata) if chunk.usage_metadata else usage
            yield _event(chunk_to_openai(chunk, model=name, **meta))
        async for chunk in rest:
            usage = dict(chunk.usage_metadata) if chunk.usage_metadata else usage
            yield _event(chunk_to_openai(chunk, model=name, **meta))
        if usage:
            yield _event(usage_chunk(usage, model=name, **meta))
    except Exception as err:
        logger.warning("gateway stream from %s failed: %s", name, type(err).__name__)
        yield _event({"error": {"message": "stream failed", "type": "upstream_error"}})
    yield "data: [DONE]\n\n"
