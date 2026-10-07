#!/usr/bin/env python3
"""Skill CLI: workspace RAG, memory, and ``Agents/`` role contracts.

This script prepares context for swarm-style tasks (provider audit, RAG snippets,
past trajectories, and the selected persona's ``AGENTS.md`` contract). Production
handoff graphs use ``langgraph_swarm.create_swarm`` with ``create_handoff_tool``
and manifests under ``Agents/*/agent.yaml`` (see ``Agents/SKILLS.md`` and
``swarm_sdk.core.swarm``).

Copyright 2026 Antigravity Team.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def skill_state_dir(workspace: Path) -> Path:
    """Return the directory for memory/RAG JSON (repo-local by default).

    Args:
        workspace: Swarm repository root.

    Returns:
        ``SWARM_SKILL_STATE_DIR`` when set, else ``{workspace}/.swarm-skill-state``.
    """
    override = os.environ.get("SWARM_SKILL_STATE_DIR")
    if override:
        path = Path(override)
    else:
        path = workspace / ".swarm-skill-state"
    path.mkdir(parents=True, exist_ok=True)
    return path

#: Max characters of a role contract embedded in the JSON payload (full file stays on disk).
CONTRACT_EXCERPT_CHARS = 4000


def find_agents_root(workspace: Path) -> Path:
    """Locate the ``Agents/`` tree for the active Swarm checkout.

    Args:
        workspace: Repository or worktree root (typically ``Path.cwd()``).

    Returns:
        Absolute path to ``Agents/``.

    Raises:
        FileNotFoundError: When no ``Agents/SKILLS.md`` exists under ``workspace``.
    """
    candidates = [workspace / "Agents", workspace.parent / "Agents"]
    anchors = ("SKILLS.md", "coordination.yaml")
    for root in candidates:
        if any((root / anchor).is_file() for anchor in anchors):
            return root.resolve()
    for root in candidates:
        if root.is_dir() and any(
            (child / "AGENTS.md").is_file() for child in root.iterdir() if child.is_dir()
        ):
            return root.resolve()
    raise FileNotFoundError(f"Agents/ not found under {workspace}")


def list_registered_agents(agents_root: Path) -> list[str]:
    """Return persona directory names that ship an ``AGENTS.md`` contract.

    Args:
        agents_root: Path returned by :func:`find_agents_root`.

    Returns:
        Sorted PascalCase names (e.g. ``Coder``, ``DeepResearch``).
    """
    names = [
        path.name
        for path in agents_root.iterdir()
        if path.is_dir() and (path / "AGENTS.md").is_file()
    ]
    return sorted(names)


def resolve_agent_name(role: str, agents_root: Path) -> str | None:
    """Map a CLI ``@coder`` / ``coder`` token to an ``Agents/{Name}`` folder.

    Args:
        role: User role or handle (leading ``@`` is stripped).
        agents_root: Swarm ``Agents/`` directory.

    Returns:
        Canonical directory name, or ``None`` when no persona matches.
    """
    token = role.lstrip("@").strip()
    if not token:
        return None
    normalized = token.lower().replace("_", "").replace("-", "")
    for name in list_registered_agents(agents_root):
        key = name.lower().replace("_", "")
        if key == normalized or name.lower() == token.lower():
            return name
    return None


def load_role_contract(
    agents_root: Path,
    agent_name: str,
    *,
    max_chars: int = CONTRACT_EXCERPT_CHARS,
) -> str:
    """Read ``Agents/{agent_name}/AGENTS.md`` (SDK helper when importable).

    Args:
        agents_root: Swarm ``Agents/`` directory.
        agent_name: Canonical persona folder name.
        max_chars: Truncate for JSON payloads; ``0`` means no truncation.

    Returns:
        Contract text, or ``""`` when the file is missing.
    """
    try:
        from swarm_sdk.agents.manifest import role_contract

        text = role_contract(str(agents_root), agent_name)
    except ImportError:
        path = agents_root / agent_name / "AGENTS.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n…"
    return text


def resolve_llm_providers() -> dict[str, dict[str, Any]]:
    """Report which cloud/local LLM env keys are set (values never returned).

    Returns:
        Map of provider label to ``status``, ``type``, and optional ``endpoint``.
        Only env vars are consulted; configure secrets with ``swarm-vault`` / ``keys``.
    """
    providers: dict[str, dict[str, Any]] = {}
    keys_map = {
        "OPENAI": "OPENAI_API_KEY",
        "ANTHROPIC": "ANTHROPIC_API_KEY",
        "GOOGLE": "GOOGLE_API_KEY",
        "DEEPSEEK": "DEEPSEEK_API_KEY",
        "GROQ": "GROQ_API_KEY",
        "OPENROUTER": "OPENROUTER_API_KEY",
        "TAVILY": "TAVILY_API_KEY",
        "BRIGHTDATA": "BRIGHTDATA_API_KEY",
    }

    for name, env_var in keys_map.items():
        key_val = os.environ.get(env_var, "")
        if key_val:
            providers[name] = {
                "status": "READY",
                "key_masked": f"{key_val[:4]}****{key_val[-4:]}" if len(key_val) >= 8 else "****",
                "type": "cloud_api",
            }
        else:
            providers[name] = {"status": "UNSET", "type": "cloud_api"}

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        res = subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                f"{ollama_host}/api/tags",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        ready = res.stdout.strip() == "200"
    except (OSError, subprocess.TimeoutExpired):
        ready = False
    providers["OLLAMA"] = {
        "status": "READY" if ready else "UNSET",
        "endpoint": ollama_host,
        "type": "local_llm",
    }

    return providers


#: Per-call completion budget by declared effort level (route label, not every
#: API exposes a reasoning-effort parameter, so this bounds output tokens).
_EFFORT_TOKEN_BUDGET = {"LOW": 512, "MEDIUM": 1024, "HIGH": 2048}

_OPENAI_COMPATIBLE_PROVIDERS = {
    "OPENAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "DEEPSEEK": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "GROQ": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "OPENROUTER": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
}


def _provider_model(provider: str, default: str) -> str:
    """Return the model for one provider, overridable by ``SWARM_SKILL_MODEL_<PROVIDER>``."""
    return os.environ.get(f"SWARM_SKILL_MODEL_{provider}", default)


def _post_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    """POST one JSON chat request and decode the JSON response.

    Raises:
        TimeoutError: The provider did not answer within ``timeout_s``.
        urllib.error.URLError: Transport failure (type-only; the message may carry hosts).
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))  # noqa: S310 - fixed https/localhost URLs


def _call_openai_compatible(
    provider: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    *,
    effort: str,
    max_ms: int,
) -> dict[str, Any]:
    """Run one chat completion against an OpenAI-compatible endpoint.

    Raises:
        TimeoutError: The call exceeded the millisecond budget.
        urllib.error.URLError: Transport failure.
        (KeyError, IndexError): The provider returned an unexpected payload shape.
    """
    endpoint, default_model = _OPENAI_COMPATIBLE_PROVIDERS[provider]
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": _provider_model(provider, default_model),
        "max_tokens": _EFFORT_TOKEN_BUDGET[effort],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    reply = _post_json(f"{endpoint}/chat/completions", headers, body, max(max_ms / 1000.0, 1.0))
    return {
        "model": str(reply.get("model", body["model"])),
        "reply": reply["choices"][0]["message"]["content"],
        "usage": reply.get("usage", {}),
    }


def _call_anthropic(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    *,
    effort: str,
    max_ms: int,
) -> dict[str, Any]:
    """Run one completion against the Anthropic messages API.

    Raises:
        TimeoutError: The call exceeded the millisecond budget.
        urllib.error.URLError: Transport failure.
        (KeyError, IndexError): Unexpected payload shape.
    """
    body = {
        "model": _provider_model("ANTHROPIC", "claude-sonnet-4-5"),
        "max_tokens": _EFFORT_TOKEN_BUDGET[effort],
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    reply = _post_json(
        "https://api.anthropic.com/v1/messages", headers, body, max(max_ms / 1000.0, 1.0)
    )
    return {
        "model": str(reply.get("model", body["model"])),
        "reply": reply["content"][0]["text"],
        "usage": reply.get("usage", {}),
    }


def execute_task_via_provider(
    provider: str,
    system_prompt: str,
    user_prompt: str,
    *,
    effort: str = "MEDIUM",
    max_ms: int = 60000,
    ollama_host: str = "http://localhost:11434",
) -> dict[str, Any]:
    """Run one real task completion against a READY provider.

    The persona contract goes in as the system prompt and the task as the user
    prompt; the ``--ms`` budget becomes the socket timeout and the effort level
    bounds output tokens. Secrets stay in env vars and never appear in errors.

    Args:
        provider: Label from :func:`resolve_llm_providers` (READY only).
        system_prompt: Persona contract text.
        user_prompt: Task text.
        effort: ``LOW`` / ``MEDIUM`` / ``HIGH`` output budget.
        max_ms: Wall-clock budget in milliseconds (socket timeout).
        ollama_host: Local endpoint for the OLLAMA provider.

    Returns:
        Dict with ``provider``, ``model``, ``reply``, ``usage``, and ``latency_ms``.

    Raises:
        ValueError: The provider has no execution adapter.
        TimeoutError: The call exceeded the millisecond budget.
        urllib.error.URLError: Transport failure (credential-free type in the CLI).
    """
    started = time.perf_counter()
    api_key = os.environ.get(f"{provider}_API_KEY", "")
    if provider in _OPENAI_COMPATIBLE_PROVIDERS:
        result = _call_openai_compatible(
            provider, api_key, system_prompt, user_prompt, effort=effort, max_ms=max_ms
        )
    elif provider == "ANTHROPIC" and api_key:
        result = _call_anthropic(
            api_key, system_prompt, user_prompt, effort=effort, max_ms=max_ms
        )
    elif provider == "OLLAMA":
        endpoint = ollama_host.rstrip("/")
        headers = {"Content-Type": "application/json"}
        body = {
            "model": _provider_model("OLLAMA", "llama3.2"),
            "max_tokens": _EFFORT_TOKEN_BUDGET[effort],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        reply = _post_json(
            f"{endpoint}/v1/chat/completions", headers, body, max(max_ms / 1000.0, 1.0)
        )
        result = {
            "model": str(reply.get("model", body["model"])),
            "reply": reply["choices"][0]["message"]["content"],
            "usage": reply.get("usage", {}),
        }
    else:
        raise ValueError(f"no execution adapter for provider {provider}")
    result["provider"] = provider
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


class FastEmbedder:
    """Local text embeddings via ``fastembed`` with a deterministic hash fallback."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        """Load ``TextEmbedding`` when the optional dependency is installed.

        Args:
            model_name: Hugging Face id passed to ``fastembed.TextEmbedding``.
        """
        self.model_name = model_name
        self.use_fastembed = False
        self._model: Any = None

        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=model_name)
            self.use_fastembed = True
        except ImportError:
            self.use_fastembed = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Vectorize each input string.

        Args:
            texts: Batch of UTF-8 strings.

        Returns:
            One float vector per input (384 dimensions in fallback mode).
        """
        if self.use_fastembed and self._model is not None:
            return [list(vec) for vec in self._model.embed(texts)]

        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * 384
            words = text.lower().split()
            for idx, word in enumerate(words):
                digest = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
                slot = digest % 384
                vec[slot] += 1.0 / (idx + 1)
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([round(v / norm, 6) for v in vec])
        return vectors


class SwarmMemoryEngine:
    """Append-only JSON store of past runs with embedding vectors for similarity search."""

    def __init__(self, embedder: FastEmbedder, state_dir: Path) -> None:
        """Open or create ``memory_db.json`` under ``state_dir``.

        Args:
            embedder: Shared embedder for prompt vectors.
            state_dir: Writable directory from :func:`skill_state_dir`.
        """
        self.embedder = embedder
        self._memory_path = state_dir / "memory_db.json"
        self.records: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self._memory_path.is_file():
            try:
                with self._memory_path.open(encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return []

    def save(self) -> None:
        """Persist ``records`` to disk."""
        with self._memory_path.open("w", encoding="utf-8") as handle:
            json.dump(self.records, handle, indent=2)

    def add_memory(self, prompt: str, result: dict[str, Any], score: float = 1.0) -> None:
        """Append one execution record.

        Args:
            prompt: Original user task text.
            result: Serializable payload stored verbatim.
            score: Quality weight in ``[0.0, 1.0]`` for ranking.
        """
        vec = self.embedder.embed([prompt])[0]
        record = {
            "id": hashlib.sha256(f"{prompt}{time.time()}".encode()).hexdigest()[:12],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prompt": prompt,
            "vector": vec,
            "result": result,
            "score": score,
        }
        self.records.append(record)
        self.save()

    def search_similar(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Rank stored trajectories by dot-product similarity.

        Args:
            query: Natural-language task description.
            top_k: Maximum rows to return.

        Returns:
            Highest-scoring memory dicts (may be empty).
        """
        if not self.records:
            return []

        query_vec = self.embedder.embed([query])[0]
        scored: list[tuple[float, dict[str, Any]]] = []

        for rec in self.records:
            rec_vec = rec.get("vector", [])
            if not rec_vec or len(rec_vec) != len(query_vec):
                continue
            dot = sum(q * r for q, r in zip(query_vec, rec_vec, strict=True))
            scored.append((dot, rec))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]


class SwarmRAGEngine:
    """Lightweight workspace indexer for markdown and shell snippets."""

    def __init__(self, embedder: FastEmbedder, workspace_dir: Path, state_dir: Path) -> None:
        """Bind embedder and root used for relative paths in the index.

        Args:
            embedder: Embedding backend shared with memory.
            workspace_dir: Repository root to walk.
            state_dir: Directory for ``rag_index.json``.
        """
        self.embedder = embedder
        self.workspace_dir = workspace_dir
        self._rag_index_path = state_dir / "rag_index.json"
        self.index: list[dict[str, Any]] = []

    def index_workspace(self, max_files: int = 50) -> int:
        """Walk the tree and embed the first matching documentation files.

        Args:
            max_files: Hard cap on indexed documents.

        Returns:
            Number of documents in ``self.index`` after the run.
        """
        documents: list[dict[str, Any]] = []
        suffixes = (".md", ".zsh")
        indexed_count = 0

        for root, _, files in os.walk(self.workspace_dir):
            if any(skip in root for skip in (".git", ".venv", "node_modules")):
                continue
            for file in files:
                if file in {"AGENTS.md", "GEMINI.md"} or file.endswith(suffixes):
                    file_path = Path(root) / file
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="ignore")[:2000]
                    except OSError:
                        continue
                    if not text.strip():
                        continue
                    documents.append(
                        {
                            "path": str(file_path.relative_to(self.workspace_dir)),
                            "content": text,
                        }
                    )
                    indexed_count += 1
                    if indexed_count >= max_files:
                        break
            if indexed_count >= max_files:
                break

        if documents:
            vectors = self.embedder.embed([doc["content"] for doc in documents])
            for doc, vec in zip(documents, vectors, strict=True):
                doc["vector"] = vec
            self.index = documents
            with self._rag_index_path.open("w", encoding="utf-8") as handle:
                json.dump(self.index, handle, indent=2)

        return len(self.index)

    def retrieve(self, query: str, top_k: int = 2) -> list[dict[str, Any]]:
        """Return the top workspace snippets for a query.

        Args:
            query: Natural-language search string.
            top_k: Number of hits.

        Returns:
            Dicts with ``path``, ``snippet``, and ``score`` keys.
        """
        if not self.index and self._rag_index_path.is_file():
            try:
                with self._rag_index_path.open(encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, list):
                    self.index = loaded
            except (OSError, json.JSONDecodeError):
                pass

        if not self.index:
            return []

        query_vec = self.embedder.embed([query])[0]
        scored: list[tuple[float, dict[str, Any]]] = []

        for doc in self.index:
            doc_vec = doc.get("vector", [])
            if not doc_vec or len(doc_vec) != len(query_vec):
                continue
            dot = sum(q * r for q, r in zip(query_vec, doc_vec, strict=True))
            scored.append((dot, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "path": item[1]["path"],
                "snippet": item[1]["content"][:300],
                "score": round(item[0], 4),
            }
            for item in scored[:top_k]
        ]


class SwarmOrchestrator:
    """Compose provider audit, RAG, memory, and ``Agents/`` contracts for one task."""

    def __init__(self, workspace_dir: Path) -> None:
        """Wire sub-engines and resolve ``Agents/`` for the workspace.

        Args:
            workspace_dir: Swarm repository root.
        """
        self.workspace_dir = workspace_dir
        self.state_dir = skill_state_dir(workspace_dir)
        self.agents_root = find_agents_root(workspace_dir)
        self.providers = resolve_llm_providers()
        self.embedder = FastEmbedder()
        self.memory = SwarmMemoryEngine(self.embedder, self.state_dir)
        self.rag = SwarmRAGEngine(self.embedder, workspace_dir, self.state_dir)

    def execute(
        self,
        prompt: str,
        role: str = "general",
        *,
        index_rag: bool = False,
        target_provider: str | None = None,
        effort: str = "MEDIUM",
        max_ms: int = 60000,
        max_try: int = 3,
    ) -> dict[str, Any]:
        """Build context for a swarm task (simulated execution latency).

        Aligns with ``langgraph_swarm.create_swarm`` handoffs in production: the
        selected persona's ``AGENTS.md`` is loaded here; a real graph would pass it
        as the agent system prompt via ``swarm_sdk`` manifests.

        Args:
            prompt: User task text.
            role: Default persona when ``target_provider`` is not an ``@agent``.
            index_rag: Force a workspace re-index before retrieval.
            target_provider: Optional ``@Coder`` handle or provider label.
            effort: Requested reasoning depth (``LOW`` / ``MEDIUM`` / ``HIGH``).
            max_ms: Declared timeout budget in milliseconds (advisory in this CLI).
            max_try: Declared retry budget (advisory in this CLI).

        Returns:
            JSON-serializable status payload including RAG and contract excerpts.
        """
        start_time = time.perf_counter()

        if index_rag or not (self.state_dir / "rag_index.json").is_file():
            self.rag.index_workspace()

        similar_past = self.memory.search_similar(prompt, top_k=2)
        rag_snippets = self.rag.retrieve(prompt, top_k=2)

        agent_name = None
        if target_provider and target_provider.lstrip("@").isalpha():
            agent_name = resolve_agent_name(target_provider, self.agents_root)
        if agent_name is None and role != "general":
            agent_name = resolve_agent_name(role, self.agents_root)

        contract_excerpt = ""
        contract_path = ""
        if agent_name:
            rel = (self.agents_root / agent_name / "AGENTS.md").relative_to(self.workspace_dir)
            contract_path = str(rel)
            contract_excerpt = load_role_contract(self.agents_root, agent_name)

        active_providers = [
            label for label, data in self.providers.items() if data["status"] == "READY"
        ]

        if target_provider and not agent_name:
            selected_provider = target_provider.upper().lstrip("@")
        elif active_providers:
            selected_provider = active_providers[0]
        else:
            selected_provider = "MOCK_ENGINE"

        # Placeholder for LangGraph ``app.invoke``; records context only.
        time.sleep(0.04)

        execution: dict[str, Any] = {
            "execution": "simulated",
            "reason": "no ready provider with an execution adapter",
        }
        if agent_name:
            ready = [
                label
                for label in (
                    "OPENAI",
                    "ANTHROPIC",
                    "DEEPSEEK",
                    "GROQ",
                    "OPENROUTER",
                    "OLLAMA",
                )
                if self.providers.get(label, {}).get("status") == "READY"
            ]
            if ready:
                contract = contract_excerpt or f"You are the {agent_name} swarm agent."
                try:
                    outcome = execute_task_via_provider(
                        ready[0],
                        contract,
                        prompt,
                        effort=effort.upper(),
                        max_ms=max_ms,
                    )
                except (
                    TimeoutError,
                    urllib.error.URLError,
                    ValueError,
                    KeyError,
                    IndexError,
                ) as err:
                    execution = {
                        "execution": "simulated",
                        "provider": ready[0],
                        "reason": f"{type(err).__name__} from provider call",
                    }
                else:
                    execution = {"execution": "real", **outcome}

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        agent_handle = f"@{agent_name}" if agent_name else (target_provider or f"@{role}")

        result_payload = {
            "status": "SUCCESS",
            "agent_target": agent_handle,
            "agent_role": agent_name or role,
            "agent_contract_path": contract_path,
            "agent_contract_excerpt_chars": len(contract_excerpt),
            "agent_contract_excerpt": contract_excerpt,
            "registered_agents_count": len(list_registered_agents(self.agents_root)),
            "prompt": prompt,
            "selected_provider": selected_provider,
            "active_providers": active_providers,
            "effort": effort.upper(),
            "max_ms": max_ms,
            "max_try": max_try,
            "latency_ms": elapsed_ms,
            "execution": execution,
            "reply": execution.get("reply"),
            "rag_context_count": len(rag_snippets),
            "retrieved_snippets": rag_snippets,
            "similar_past_count": len(similar_past),
            "fastembed_active": self.embedder.use_fastembed,
            "langgraph_note": (
                "Production swarm: langgraph_swarm.create_swarm + create_handoff_tool "
                "(see Agents/SKILLS.md)"
            ),
        }

        self.memory.add_memory(prompt, result_payload, score=0.99)
        return result_payload


def main() -> None:
    """Parse ``@agent`` tokens and dispatch :class:`SwarmOrchestrator`."""
    target_agent: str | None = None
    cleaned_argv: list[str] = []

    for arg in sys.argv[1:]:
        if arg.startswith("@"):
            target_agent = arg
        else:
            cleaned_argv.append(arg)

    parser = argparse.ArgumentParser(
        description="Swarm skill CLI (RAG, memory, Agents/ contracts)",
    )
    parser.add_argument("--prompt", "-p", "--Task", "-t", dest="prompt", type=str)
    parser.add_argument("--role", type=str, default="general", help="Persona when @agent omitted")
    parser.add_argument(
        "--Effort",
        "--effort",
        dest="effort",
        type=str,
        default="MEDIUM",
        choices=["LOW", "MEDIUM", "HIGH", "low", "medium", "high"],
    )
    parser.add_argument("--MaxMS", "--max-ms", "--ms", dest="max_ms", type=int, default=60000)
    parser.add_argument("--MaxTry", "--max-try", dest="max_try", type=int, default=3)
    parser.add_argument("--index-rag", action="store_true", help="Rebuild workspace RAG index")
    parser.add_argument("--status", action="store_true", help="Provider, memory, and agent roster")
    args = parser.parse_args(cleaned_argv)

    workspace = Path.cwd()
    orchestrator = SwarmOrchestrator(workspace)

    roster = list_registered_agents(orchestrator.agents_root)
    if target_agent:
        token = target_agent.lstrip("@").strip()
        if not resolve_agent_name(token, orchestrator.agents_root) and token.upper() not in {
            label.upper() for label in orchestrator.providers
        }:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "unknown_agent": target_agent,
                        "registered_agents": roster,
                        "hint": (
                            "Use an Agents/ folder name (case-insensitive, "
                            "'-' and '_' ignored), or a provider label."
                        ),
                    },
                    indent=2,
                )
            )
            raise SystemExit(2)

    if args.status or not args.prompt:
        print(
            json.dumps(
                {
                    "swarm_status": "ONLINE",
                    "active_llm_providers": orchestrator.providers,
                    "fastembed_enabled": orchestrator.embedder.use_fastembed,
                    "memory_records_count": len(orchestrator.memory.records),
                    "rag_indexed_count": len(orchestrator.rag.index),
                    "agents_root": str(orchestrator.agents_root.relative_to(workspace)),
                    "registered_agents": list_registered_agents(orchestrator.agents_root),
                },
                indent=2,
            )
        )
        return

    result = orchestrator.execute(
        prompt=args.prompt,
        role=args.role,
        index_rag=args.index_rag,
        target_provider=target_agent,
        effort=args.effort,
        max_ms=args.max_ms,
        max_try=args.max_try,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
