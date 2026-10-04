"""Mem0 memory backend. Imported only when the ``mem0`` extra is installed.

Uses the hosted Platform ``MemoryClient`` (``MEM0_API_KEY``). OSS ``Memory`` is
not wired here: it needs a local LLM/embedder stack. Tests inject a fake client.
Mem0 embeds and ranks internally, so ``search`` ignores the query vector —
:meth:`search_text` is the recall path.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np

from swarm_sdk.memory.base import MemoryHit

if TYPE_CHECKING:
    from swarm_sdk.config.settings import Settings

_CACHE_HEAD = "swarm-cache"


def _vault_secret(name: str) -> str:
    """Keychain value for ``name``, or empty. The value is not logged."""
    try:
        from swarm_sdk.vault import get
    except ImportError:
        return ""
    try:
        return get(name) or ""
    except OSError, ValueError:
        return ""


class Mem0Client(Protocol):
    """Minimal subset of ``mem0.MemoryClient`` used by :class:`Mem0Store`."""

    def add(self, messages: object, **kwargs: object) -> object: ...

    def search(self, query: str, **kwargs: object) -> object: ...


def _rows(payload: object) -> list[dict[str, object]]:
    """Normalize Mem0 add/search payloads to a list of result dicts."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _hit_id(raw: object) -> int:
    """Map a Mem0 UUID (or int) onto ``MemoryHit.id`` (int64-safe)."""
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    text = str(raw)
    if text.isdigit():
        return int(text)
    digest = hashlib.blake2s(text.encode(), digest_size=4).hexdigest()
    return int(digest, 16)


def _hit_text(row: dict[str, object]) -> str:
    """Prefer Mem0's ``memory`` field, then ``text``."""
    for key in ("memory", "text", "data"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


class Mem0Store:
    """``MemoryStore`` adapter over Mem0 Platform ``add`` / ``search``.

    Args:
        client: Pre-built ``MemoryClient`` (or a test double).
        user_id: Mem0 entity id; always sent on add and as a search filter.
        agent_id: Optional agent scope stored on add.
        infer: When True, Mem0 extracts structured memories (extra LLM call).
            Default False stores the swarm Q/A record as-is.
    """

    def __init__(
        self,
        client: Mem0Client,
        *,
        user_id: str = "swarm",
        agent_id: str = "swarm-sdk",
        infer: bool = False,
    ) -> None:
        """Initialize the store from settings (platform client or local table)."""
        self._client = client
        self.user_id = user_id
        self.agent_id = agent_id
        self.infer = infer
        self._next_id = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> Mem0Store:
        """Build a store from ``SWARM_MEM0_*`` / ``MEM0_API_KEY`` settings.

        Raises:
            RuntimeError: When the named API-key env var is unset, or ``mem0ai``
                is not installed (``uv sync --extra mem0``).
        """
        env_name = settings.mem0_api_key_env
        api_key = os.environ.get(env_name) or _vault_secret(env_name)
        if not api_key:
            raise RuntimeError(f"api key env var {env_name} is not set for mem0 memory")
        try:
            from mem0 import MemoryClient
        except ImportError as exc:
            raise RuntimeError("mem0 backend requires uv sync --extra mem0") from exc
        client = cast(Mem0Client, MemoryClient(api_key=api_key))
        return cls(
            client,
            user_id=settings.mem0_user_id,
            agent_id=settings.mem0_agent_id,
            infer=settings.mem0_infer,
        )

    def add(self, text: str, vector: np.ndarray) -> int:
        """Store a memory via the Mem0 Platform client."""
        del vector
        payload = self._client.add(
            [{"role": "user", "content": text}],
            user_id=self.user_id,
            agent_id=self.agent_id,
            infer=self.infer,
        )
        rows = _rows(payload)
        if rows:
            return _hit_id(rows[0].get("id", rows[0].get("event_id")))
        self._next_id += 1
        return self._next_id

    def put(self, key: str, value: str) -> None:
        """Store ``value`` under ``key`` (header line, epoch seconds, then the value)."""
        body = f"{_CACHE_HEAD}:{key}\n{int(time.time())}\n{value}"
        self._client.add(
            [{"role": "user", "content": body}],
            user_id=self.user_id,
            agent_id=self.agent_id,
            infer=False,
        )

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None:
        """Return the newest non-expired value stored under ``key``, else None."""
        header = f"{_CACHE_HEAD}:{key}"
        payload = self._client.search(header, filters={"user_id": self.user_id}, top_k=5)
        best: tuple[int, str] | None = None
        for row in _rows(payload):
            first, _, rest = _hit_text(row).partition("\n")
            if first != header:
                continue
            stamp, sep, value = rest.partition("\n")
            if not sep or not stamp.isdigit():
                continue
            if max_age_s is not None and time.time() - int(stamp) > max_age_s:
                continue
            if best is None or int(stamp) >= best[0]:
                best = (int(stamp), value)
        return best[1] if best else None

    def search_text(self, query: str, k: int) -> list[MemoryHit]:
        """Semantic search over Mem0 using the natural-language query."""
        if k < 1 or not query.strip():
            return []
        payload = self._client.search(
            query,
            filters={"user_id": self.user_id},
            top_k=k,
        )
        hits: list[MemoryHit] = []
        for row in _rows(payload)[:k]:
            text = _hit_text(row)
            if not text:
                continue
            score = row.get("score", 1.0)
            hits.append(
                MemoryHit(
                    id=_hit_id(row.get("id")),
                    text=text,
                    score=float(score) if isinstance(score, int | float) else 1.0,
                )
            )
        return hits

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        """Vector search is unused: Mem0 ranks by text. Returns no hits.

        Callers that have the original query should use :meth:`search_text`.
        """
        del vector, k
        return []
