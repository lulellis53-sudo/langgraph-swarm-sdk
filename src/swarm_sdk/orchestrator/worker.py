"""Worker agents: one manifest + role contract per spawned agent."""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import TYPE_CHECKING

from swarm_sdk.agents.manifest import AgentManifest

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
from swarm_sdk.cache import SemanticCache
from swarm_sdk.providers import complete, load_chat_model
from swarm_sdk.tokens import TokenBudget, count_text

from .plan import StepOutput


@lru_cache(maxsize=32)
def role_contract(agents_root: str, name: str) -> str:
    """Role contract text (Agents/{Name}/AGENTS.md), cached per process."""
    from pathlib import Path

    path = Path(agents_root) / name / "AGENTS.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


class WorkerAgent:
    """Single-step worker bound to one agent manifest.

    The system prompt is the role contract from the agent's AGENTS.md; the user
    prompt carries only the step description plus the declared dependency outputs
    — never the whole transcript (token saving).
    """

    def __init__(
        self,
        manifest: AgentManifest,
        *,
        agents_root: str,
        cache: SemanticCache | None = None,
        model_override: BaseChatModel | None = None,
    ) -> None:
        self.manifest = manifest
        self.agents_root = agents_root
        self.cache = cache
        self._model = model_override
        self.tokens = TokenBudget(max_tokens=manifest.token_budget.max_prompt)

    @property
    def name(self) -> str:
        return self.manifest.name

    def _system_prompt(self) -> str:
        contract = role_contract(self.agents_root, self.manifest.name)
        packed = self.tokens.pack(system=contract or self.manifest.role, memories=[], turns=[])
        return packed.system

    def _user_prompt(self, description: str, dep_outputs: dict[str, str]) -> str:
        parts = [description.strip()]
        if dep_outputs:
            parts.append("inputs:")
            parts.extend(f"- {k}: {v}" for k, v in dep_outputs.items())
        user = "\n".join(parts)
        budget = self.tokens
        system = self._system_prompt()
        if budget.count(f"{system}\n{user}") > budget.max_tokens:
            user = budget._truncate(user, max(1, budget.max_tokens - budget.count(system)))
        return user

    def _model_name(self) -> str:
        name = self.manifest.model
        if not name:
            raise RuntimeError(f"agent {self.name} has no model in its manifest")
        return name

    def _resolve_api_key(self) -> None:
        """Point the provider SDK at the key named by `api_key_env` (never the key itself)."""
        env = self.manifest.api_key_env
        if not env:
            return
        value = os.environ.get(env)
        if not value:
            raise RuntimeError(f"api key env var {env} is not set for agent {self.name}")
        provider = self._model_name().split(":", 1)[0].upper()
        os.environ.setdefault(f"{provider}_API_KEY", value)

    async def run(self, step_id: str, description: str, dep_outputs: dict[str, str]) -> StepOutput:
        system = self._system_prompt()
        user = self._user_prompt(description, dep_outputs)
        cache_key = f"{self.name}\n{system}\n{user}"
        started = time.perf_counter()

        if self.cache is not None:
            hit = self.cache.lookup(cache_key)
            if hit is not None:
                return StepOutput(
                    step_id=step_id,
                    agent=self.name,
                    content=hit,
                    cached=True,
                    wall_s=time.perf_counter() - started,
                )

        self._resolve_api_key()
        model = self._model if self._model is not None else load_chat_model(self._model_name())
        content = await complete(model, system, user)
        wall = time.perf_counter() - started

        if self.cache is not None:
            self.cache.store(cache_key, content)

        return StepOutput(
            step_id=step_id,
            agent=self.name,
            content=content,
            prompt_tokens=count_text(f"{system}\n{user}"),
            completion_tokens=count_text(content),
            wall_s=wall,
        )
