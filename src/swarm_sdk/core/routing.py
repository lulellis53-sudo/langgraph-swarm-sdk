"""Router decision model and model-backed routing for the swarm SDK."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, ValidationError

from swarm_sdk.core.prompts import ROUTER_SYSTEM
from swarm_sdk.execution import offload
from swarm_sdk.models.chat import complete_with_usage, message_tokens
from swarm_sdk.prompting.budget import PackedPrompt, count_text

if TYPE_CHECKING:
    from swarm_sdk.core.swarm import SwarmSDK

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class RouteDecision(BaseModel):
    """Router verdict: ``swarm`` handoff or ``parallel`` fan-out with task texts."""

    mode: Literal["parallel", "swarm"] = "swarm"
    tasks: list[str] = Field(default_factory=list)


def _parse_route(raw: str) -> RouteDecision:
    """Parse router output, defaulting to ``RouteDecision()`` on anything malformed."""
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return RouteDecision()
    try:
        return RouteDecision.model_validate(json.loads(match.group(0)))
    except json.JSONDecodeError, ValidationError:
        return RouteDecision()


class Router:
    """Model-backed router: structured output with JSON-mode + regex fallback."""

    def __init__(self, sdk: SwarmSDK) -> None:
        self._sdk = sdk

    async def route_structured(self, user: str) -> tuple[RouteDecision | None, int]:
        """Ask the router for a ``RouteDecision`` via LangChain tool-calling.

        Args:
            user: The packed router prompt body (memories + user text).

        Returns:
            ``(decision, tokens)`` on a parseable reply, else ``(None, 0)`` so
            the caller falls back to the JSON-mode + regex path.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            structured = self._sdk._router_model_loader().with_structured_output(
                RouteDecision, include_raw=True
            )
        except NotImplementedError:
            return None, 0
        result = await offload(
            structured.invoke,
            [SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=user)],
        )
        if not isinstance(result, dict):
            return None, 0
        parsed = result.get("parsed")
        if not isinstance(parsed, RouteDecision):
            return None, 0
        tokens = message_tokens(result.get("raw"))
        if tokens is None:
            tokens = count_text(ROUTER_SYSTEM) + count_text(user)
        return parsed, tokens

    async def route(self, packed: PackedPrompt) -> tuple[RouteDecision, int]:
        """Choose parallel fan-out or swarm handoff, returning the decision and tokens used."""
        sdk = self._sdk
        user = packed.suffix or packed.prefix
        if sdk.settings.router_structured_output:
            # Prefer schema-constrained output; fall back to JSON-mode text when unsupported.
            decision, tokens = await self.route_structured(user)
            if decision is not None:
                return decision, tokens
        json_mode = sdk.settings.router_structured_output
        if sdk.settings.model:
            raw, tokens = await offload(
                complete_with_usage,
                sdk._router_model_loader(),
                ROUTER_SYSTEM,
                user,
                json_mode=json_mode,
            )
        elif sdk._router_model is not None:
            raw, tokens = await complete_with_usage(
                sdk._router_model,
                ROUTER_SYSTEM,
                user,
                json_mode=json_mode,
            )
        else:
            raw, tokens = await sdk._fallback.complete_with_usage(
                ROUTER_SYSTEM,
                user,
                think_level=sdk.file_config.router.think_level,
                json_mode=json_mode,
            )
        # Lenient parse: malformed or adversarial router output degrades to a safe default route.
        return _parse_route(raw), tokens


__all__ = ["RouteDecision", "Router", "_parse_route"]
