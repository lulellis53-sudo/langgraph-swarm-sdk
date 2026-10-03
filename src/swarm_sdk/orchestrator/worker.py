"""Worker agents: one manifest + role contract per spawned agent.

A :class:`WorkerAgent` is the runtime half of an ``Agents/{Name}/`` persona:

* the **system prompt** is the role contract from that agent's ``AGENTS.md``
  (loaded once per process, truncated to the manifest's ``max_prompt`` budget);
* the **user prompt** is the step description plus only the dependency outputs
  the step declared in ``inputs`` — never the whole transcript, which is the
  main token-saving lever of the engine;
* the **model, think level, effort, and token budget** come pre-selected from
  the agent's ``agent.yaml`` manifest.

Optionally a :class:`~swarm_sdk.retrieval.cache.SemanticCache` is consulted per step on
the ``(agent, system, user)`` triple: a hit skips the LLM call entirely.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from swarm_sdk.agents.manifest import AgentManifest, role_contract
from swarm_sdk.models.chat import complete, load_chat_model
from swarm_sdk.prompting.budget import TokenBudget, count_text
from swarm_sdk.retrieval.cache import SemanticCache

from .plan import StepOutput

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

__all__ = ["WorkerAgent", "role_contract"]


class WorkerAgent:
    """Single-step worker bound to one agent manifest.

    Instances are cheap: the heavy objects (model client, role contract) are
    created lazily or cached at module level, so the engine builds a fresh
    worker per step without penalty (fresh-agent-per-attempt factory contract).

    Args:
        manifest: The validated ``agent.yaml`` manifest for this agent.
        agents_root: Directory holding the ``Agents/{Name}/`` folders; used to
            resolve the role contract.
        cache: Optional semantic/exact cache; when set, answered steps are
            stored and repeated steps are answered without an LLM call.
        model_override: Optional pre-built chat model (tests, scripted runs).
            When ``None`` the model is loaded from ``manifest.model``.
    """

    def __init__(
        self,
        manifest: AgentManifest,
        *,
        agents_root: str,
        cache: SemanticCache | None = None,
        model_override: BaseChatModel | None = None,
    ) -> None:
        """Bind one agent manifest; heavy objects load lazily.

        Args:
            manifest: Validated ``agent.yaml`` for this persona.
            agents_root: Directory holding the ``Agents/{Name}/`` folders.
            cache: Optional semantic/exact cache for step answers.
            model_override: Pre-built chat model (tests); None loads from the manifest.
        """
        self.manifest = manifest
        self.agents_root = agents_root
        self.cache = cache
        self._model = model_override
        # The TokenBudget enforces the manifest's max_prompt cap on packing.
        self.tokens = TokenBudget(max_tokens=manifest.token_budget.max_prompt)

    @property
    def name(self) -> str:
        """Agent name from the manifest (directory name under Agents/)."""
        return self.manifest.name

    def _system_prompt(self) -> str:
        """Build the system prompt: role contract packed under the token cap.

        Returns:
            The role contract text, truncated so it alone fits the budget.
            Falls back to the manifest's ``role`` string when the agent has no
            AGENTS.md contract file.
        """
        contract = role_contract(self.agents_root, self.manifest.name)
        packed = self.tokens.pack(system=contract or self.manifest.role, memories=[], turns=[])
        return packed.system

    def _user_prompt(
        self,
        description: str,
        dep_outputs: dict[str, str],
        *,
        files: list[str] | None = None,
        task: str = "",
    ) -> str:
        """Build the user prompt: step description + task/files + declared inputs.

        Args:
            description: The step instruction (from the plan).
            dep_outputs: Outputs of the steps this step declared in ``inputs``.
            files: Exclusive write-paths claimed by this step (Coder partition).
            task: Optional ``agent.yaml`` task id.

        Returns:
            The packed user prompt, truncated so ``system + user`` fits the
            manifest's ``max_prompt`` budget.
        """
        parts = [description.strip()]
        if task:
            parts.append(f"task: {task}")
        if files:
            parts.append("files:")
            parts.extend(f"- {path}" for path in files)
        if dep_outputs:
            parts.append("inputs:")
            parts.extend(f"- {k}: {v}" for k, v in dep_outputs.items())
        user = "\n".join(parts)
        budget = self.tokens
        system = self._system_prompt()
        if budget.count(f"{system}\n{user}") > budget.max_tokens:
            # Leave whatever room the system prompt does not consume.
            remaining = max(0, budget.max_tokens - budget.count(system))
            user = budget.truncate(user, remaining)
        return user

    def _model_name(self) -> str:
        """Manifest model string (LangChain init format), validated non-empty.

        Raises:
            RuntimeError: When the manifest declares no model.
        """
        name = self.manifest.model
        if not name:
            raise RuntimeError(f"agent {self.name} has no model in its manifest")
        return name

    def _resolve_api_key(self) -> None:
        """Expose the provider API key to the SDK, named by ``api_key_env``.

        The manifest stores only the *name* of the environment variable that
        holds the key — the secret value itself never lives in the repo. The
        value is copied to the provider-specific variable (e.g.
        ``OPENAI_API_KEY``) that LangChain's ``init_chat_model`` reads, using
        ``setdefault`` so an explicitly configured environment wins.

        Raises:
            RuntimeError: When neither the named env var nor the provider's own key
                (``<PROVIDER>_API_KEY``) is set at call time.
        """
        env = self.manifest.api_key_env
        if not env:
            return
        provider_env = f"{self._model_name().split(':', 1)[0].upper()}_API_KEY"
        from swarm_sdk import vault

        value = os.environ.get(env) or vault.get(env)
        if not value:
            # Per-agent override unset: the provider's own key (e.g. primed from the
            # Keychain by prime_runtime_secrets) is enough.
            if os.environ.get(provider_env):
                return
            raise RuntimeError(f"api key env var {env} is not set for agent {self.name}")
        os.environ.setdefault(provider_env, value)

    async def run(
        self,
        step_id: str,
        description: str,
        dep_outputs: dict[str, str],
        *,
        files: list[str] | None = None,
        task: str = "",
    ) -> StepOutput:
        """Execute one plan step.

        Order of operations: build prompts → consult cache → (on miss) resolve
        the API key → load/build the model → call the provider → store in cache
        → return a :class:`StepOutput` with token counts and wall time.

        Args:
            step_id: Id of the plan step being executed.
            description: Step instruction used as the user prompt body.
            dep_outputs: Declared inputs (dependency outputs) to inject.
            files: Exclusive write-paths claimed by this step.
            task: Optional ``agent.yaml`` task id.

        Returns:
            The step output. Cache hits carry ``cached=True`` and zero token
            counts; misses carry approximate counts from the whitespace
            tokenizer.
        """
        system = self._system_prompt()
        user = self._user_prompt(description, dep_outputs, files=files, task=task)
        # Cache identity is the full (agent, system, user) triple: same role,
        # same question → same answer is a safe assumption at threshold 0.97.
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

        # Empty replies must not poison the cache: a later near-identical step
        # would be answered with nothing instead of calling the model.
        if self.cache is not None and content.strip():
            self.cache.store(cache_key, content)

        return StepOutput(
            step_id=step_id,
            agent=self.name,
            content=content,
            prompt_tokens=count_text(f"{system}\n{user}" if user else system),
            completion_tokens=count_text(content),
            wall_s=wall,
        )
