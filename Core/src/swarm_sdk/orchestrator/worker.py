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

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from swarm_sdk.agents.handoff import handoff_errors
from swarm_sdk.agents.manifest import AgentManifest, role_contract
from swarm_sdk.execution import offload
from swarm_sdk.models.chat import complete, load_chat_model, message_text, ordered_key_names
from swarm_sdk.prompting.budget import TokenBudget, count_text
from swarm_sdk.retrieval.cache import SemanticCache

from .plan import StepOutput

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

__all__ = ["WorkerAgent", "role_contract"]

#: Model rounds that may call ``parse_syntax`` before the worker keeps the reply.
_AST_TOOL_ROUNDS = 2


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
        # Cache the system prompt: it is deterministic per manifest + agents_root.
        self._system_cache: str | None = None

    @property
    def name(self) -> str:
        """Agent name from the manifest (directory name under Agents/)."""
        return self.manifest.name

    def _system_prompt(self) -> str:
        """Build the system prompt: role contract packed under the token cap.

        The result is cached per instance — the role contract is deterministic
        for a given (manifest, agents_root) pair.

        Returns:
            The role contract text, truncated so it alone fits the budget.
            Falls back to the manifest's ``role`` string when the agent has no
            AGENTS.md contract file.
        """
        if self._system_cache is not None:
            return self._system_cache
        contract = role_contract(self.agents_root, self.manifest.name)
        packed = self.tokens.pack(system=contract or self.manifest.role, memories=[], turns=[])
        self._system_cache = packed.system
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
        from swarm_sdk.prompting.pruner import TurnPruner

        parts = [description.strip()]
        if task:
            parts.append(f"task: {task}")
        if files:
            parts.append("files:")
            parts.extend(f"- {path}" for path in files)
        if dep_outputs:
            # Compress dependency outputs to reduce prompt tokens.
            pruner = TurnPruner(keep_turns=len(dep_outputs), max_tokens=2000)
            compressed = pruner.prune(list(dep_outputs.values()))
            # Rebuild the mapping with compressed values.
            keys = list(dep_outputs.keys())
            if len(compressed) == len(keys):
                dep_outputs = dict(zip(keys, compressed))
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

    def _resolve_api_key(self, model_name: str | None = None, api_key_env: str | None = None) -> None:
        """Expose the provider API key to the SDK, named by ``api_key_env``.

        The manifest stores only the *name* of the environment variable that
        holds the key — the secret value itself never lives in the repo. The
        value is copied to the provider-specific variable (e.g.
        ``OPENAI_API_KEY``) that LangChain's ``init_chat_model`` reads, using
        ``setdefault`` so an explicitly configured environment wins.
        """
        target_model = model_name or self._model_name()
        env = api_key_env or self.manifest.api_key_env
        provider_env = f"{target_model.split(':', 1)[0].upper()}_API_KEY"
        from swarm_sdk import vault

        names = ordered_key_names(target_model, env)
        value = ""
        for name in names:
            value = os.environ.get(name) or vault.get(name) or ""
            if value:
                break
        if not value:
            val = os.environ.get(provider_env) or vault.get(provider_env)
            if val:
                os.environ.setdefault(provider_env, val)
                return
            return
        os.environ.setdefault(provider_env, value)

    def _candidate_models(self) -> list[tuple[str, str | None]]:
        """Return list of (model_name, api_key_env) in fallback order."""
        candidates: list[tuple[str, str | None]] = []
        if self._model is not None:
            return [(self.manifest.model or "custom", None)]

        # Check <agents_root>/<name>/config/models.yaml
        models_yaml_path = Path(self.agents_root) / self.name / "config" / "models.yaml"
        if models_yaml_path.is_file():
            import yaml

            try:
                data = yaml.safe_load(models_yaml_path.read_text(encoding="utf-8")) or {}
                models_dict = data.get("models") or {}
                chain_order = data.get("fallback_chain", {}).get("order", ["primary", "fallback"])
                for key in chain_order:
                    if key in models_dict and isinstance(models_dict[key], dict):
                        m_name = models_dict[key].get("name")
                        m_env = models_dict[key].get("api_key_env")
                        if m_name and not any(c[0] == m_name for c in candidates):
                            candidates.append((m_name, m_env))
            except Exception as e:
                logger.warning("failed to load %s: %s", models_yaml_path, e)

        # Fallback to manifest model
        manifest_model = self.manifest.model
        if manifest_model and not any(c[0] == manifest_model for c in candidates):
            candidates.insert(0, (manifest_model, self.manifest.api_key_env))

        # Always ensure verified high-speed free fallbacks exist in reserve
        free_fallbacks = [
            ("cerebras:gpt-oss-120b", "CEREBRAS_API_KEY"),
            ("cerebras:qwen-3.8-27b", "CEREBRAS_API_KEY"),
            ("mistral:codestral-latest", "MISTRAL_API_KEY"),
        ]
        for fb_model, fb_env in free_fallbacks:
            if not any(c[0] == fb_model for c in candidates):
                candidates.append((fb_model, fb_env))

        return candidates

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

        content = ""
        last_error: Exception | None = None
        candidates = self._candidate_models() if self._model is None else [(self.manifest.model or "custom", None)]

        for model_name, key_env in candidates:
            try:
                if self._model is not None:
                    model = self._model
                else:
                    self._resolve_api_key(model_name, key_env)
                    model = load_chat_model(model_name)

                if "ast" in self.manifest.capabilities:
                    content = await self._complete_with_syntax(model, system, user)
                else:
                    content = await complete(model, system, user)
                if content:
                    break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "candidate model %s failed for %s (%s: %s); trying fallback",
                    model_name,
                    self.name,
                    type(exc).__name__,
                    exc,
                )
                continue

        if not content and last_error is not None:
            raise last_error

        wall = time.perf_counter() - started

        errors = handoff_errors(self.agents_root, self.name, content)
        status = "blocked" if errors else "ok"
        # Empty replies and invalid handoffs must not poison the cache.
        if self.cache is not None and content.strip() and status == "ok":
            self.cache.store(cache_key, content)

        return StepOutput(
            step_id=step_id,
            agent=self.name,
            content=content,
            prompt_tokens=count_text(f"{system}\n{user}" if user else system),
            completion_tokens=count_text(content),
            wall_s=wall,
            status=status,
            handoff_errors=errors,
        )

    async def _complete_with_syntax(self, model: BaseChatModel, system: str, user: str) -> str:
        """Call the model with ``parse_syntax`` bound, at most two tool rounds.

        Args:
            model: Chat model for this step. A model that cannot bind tools is
                called as plain text.
            system: Role contract.
            user: Step prompt.

        Returns:
            The final reply text. If the model is still asking for a tool when
            the round cap is reached, the last outline is the reply.
        """
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        from swarm_sdk.agents.syntax_tree import outline_source, syntax_tools

        tools = syntax_tools()
        bind = getattr(model, "bind_tools", None)
        if not callable(bind):
            return await complete(model, system, user)
        try:
            bound = bind(tools)
        except NotImplementedError, TypeError, ValueError:
            return await complete(model, system, user)

        messages: list[object] = [SystemMessage(content=system), HumanMessage(content=user)]
        last_outline = ""
        for round_index in range(_AST_TOOL_ROUNDS + 1):
            payload = list(messages)

            def _invoke(batch: list[object] = payload) -> object:
                return bound.invoke(batch)

            result = await offload(_invoke)
            calls = getattr(result, "tool_calls", None) or []
            if not calls or round_index == _AST_TOOL_ROUNDS:
                text = message_text(result)
                return text or last_outline
            messages.append(result)
            for call in calls:
                if not isinstance(call, dict):
                    continue
                args = call.get("args")
                if not isinstance(args, dict):
                    args = {}
                source = args.get("source", "")
                language = args.get("language", "python")
                last_outline = outline_source(
                    source if isinstance(source, str) else "",
                    language if isinstance(language, str) else "python",
                )
                messages.append(
                    ToolMessage(content=last_outline, tool_call_id=str(call.get("id", "")))
                )
        return last_outline
