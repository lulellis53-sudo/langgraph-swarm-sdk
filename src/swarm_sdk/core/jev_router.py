"""Jev AI System-1 non-autoregressive decision engine.

Provides sub-35ms routing for:
1. NoulDecision: Binary assertion verifying task safety and sandbox compliance.
2. ScoreDecision: Complexity score in [0.0, 1.0] mapping to model tier (flash_lite, flash, pro).
3. ChoiceDecision: Direct discrete routing across candidate agent roles.

Supports remote Jev microservice integration with Keychain / vault credentials
and a sub-10ms local deterministic semantic classification engine fallback.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, ClassVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic v2 Decision Models
# ---------------------------------------------------------------------------


class NoulDecision(BaseModel):
    """Binary safety gate decision."""

    decision: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_tag: str
    latency_ms: float


class ScoreDecision(BaseModel):
    """Task complexity scoring and model tiering decision."""

    score: float = Field(ge=0.0, le=1.0)
    model_tier: str  # "flash_lite", "flash", "pro"
    complexity_bucket: str  # "low", "medium", "high"
    latency_ms: float


class ChoiceDecision(BaseModel):
    """Discrete routing decision among candidate options."""

    selected_choice: str
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)
    latency_ms: float


# ---------------------------------------------------------------------------
# Compiled Semantic Patterns for Local Fallback Classification
# ---------------------------------------------------------------------------

# Noul Unsafe Patterns
_RE_DESTRUCTIVE_RM = re.compile(
    r"(?i)\brm\s+-(?:[a-z]*r[a-z]*f|[a-z]*f[a-z]*r)\b.*(?:\s+/|\s+~|\s+\*|etc|system|library)",
)
_RE_FORK_BOMB = re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:|:\(\)\{.*:\|:&.*\};:")
_RE_DISK_CORRUPT = re.compile(
    r"(?i)(?:\bmkfs(?:\.[a-z0-9]+)?\s+|\bdd\s+if=.*of=(?:/dev/|[a-z0-9_]+)|\bchmod\s+-R\s+777\s+/|\b(?:fdisk|parted)\b)",
)
_RE_PIPE_TO_SHELL = re.compile(
    r"(?i)\b(?:curl|wget|fetch)\b[^\n|;&]*\|\s*(?:bash|sh|zsh|dash|python[0-9.]*|perl|ruby)",
)
_RE_SECRET_EXFILTRATION = re.compile(
    r"(?i)\b(?:exfiltrat\w*|leak\w*|steal\w*|dump\w*)\b[^\n]*(?:key|token|secret|password|credential|\.env|id_rsa)|"
    r"(?:cat|grep|less|head|tail|curl|wget)\b[^\n]*(?:\.env|id_rsa|id_ed25519|/etc/shadow|/etc/passwd)[^\n|;&]*(?:\|\s*(?:curl|wget|nc|netcat|ncat|socat)|-d\s+@|-X\s+POST)|"
    r"(?:tar|zip)\b[^\n]*(?:\.ssh|\.gnupg|\.aws)[^\n]*\|\s*(?:nc|curl|wget)|"
    r"\bcurl\b[^\n]*-d\s+@[^\n]*(?:passwd|shadow|\.env|id_rsa)",
)

_RE_MALICIOUS_OPS = re.compile(
    r"(?i)(?:\b(?:nc|netcat|ncat|socat)\b[^\n]*-[a-z]*e\s+|"
    r"\b(?:nc|netcat|ncat|socat)\b[^\n]*\b(?:\d{1,3}\.){3}\d{1,3}\b\s+\d+|"
    r"/bin/(?:ba)?sh\s+-i)",
)

# Score Pro Patterns (score >= 0.75 -> "pro", "high")
_RE_PRO_MULTI_FILE = re.compile(
    r"(?i)\b(?:multi-?file|cross-module|across\s+modules|multiple\s+modules|across\s+files|multiple\s+files)\b"
)
_RE_PRO_ARCHITECTURE = re.compile(
    r"(?i)\b(?:architectur(?:al|e)|overhaul|redesign|clean\s+architecture)\b"
)
_RE_PRO_CONCURRENCY = re.compile(
    r"(?i)\b(?:concurrency|concurrent|thread-safe|race\s+condition|deadlock|mutex|semaphore|lock-free|multi-threaded|thread\s+pool)\b"
)
_RE_PRO_LOW_LEVEL = re.compile(
    r"(?i)\b(?:simd|avx2|avx-?512|opencl|gpu\s+kernel|cuda|vulkan|numa|zero-copy|ring\s+buffer|memory\s+allocator)\b"
)
_RE_PRO_DISTRIBUTED = re.compile(r"(?i)\b(?:distributed|consensus|raft|paxos|state\s+machine)\b")

# Score Low Patterns (score < 0.40 -> "flash_lite", "low")
_RE_LOW_TYPO = re.compile(
    r"(?i)\b(?:typo|typos|spelling|rename\s+local|rename\s+variable|rename\s+parameter)\b"
)
_RE_LOW_DOCS = re.compile(
    r"(?i)\b(?:docstring|docstrings|add\s+docstring|update\s+docstring|readme|comment|comments)\b"
)
_RE_LOW_FORMAT = re.compile(
    r"(?i)\b(?:format\s+code|formatting|ruff\s+check|whitespace|indentation|lint|style\s+fix)\b"
)
_RE_LOW_LOOKUP = re.compile(
    r"(?i)\b(?:lookup|find\s+symbol|find\s+usages|search\s+symbol|definition\s+in\s+index|symbol\s+definition)\b"
)

# Candidate Semantic Associations for Choice Routing
_CANDIDATE_KEYWORDS: dict[str, list[str]] = {
    "coder": [
        "implement",
        "code",
        "create",
        "build",
        "add",
        "feature",
        "endpoint",
        "function",
        "class",
        "module",
        "write function",
        "develop",
    ],
    "tester": [
        "test",
        "tests",
        "pytest",
        "unit test",
        "integration test",
        "assert",
        "coverage",
        "verify",
        "benchmark",
        "mock",
        "spec",
    ],
    "reviewer": [
        "review",
        "inspect",
        "audit",
        "diff",
        "pr",
        "pull request",
        "check",
        "lint",
        "security review",
        "vulnerabilit",
    ],
    "refactor": [
        "refactor",
        "refactoring",
        "restructure",
        "rewrite",
        "clean up",
        "cleanup",
        "reorganize",
        "decouple",
        "optimize architecture",
    ],
}


def _softmax(scores: list[float], temperature: float = 1.0) -> list[float]:
    """Compute softmax probabilities with numerical stability."""
    if not scores:
        return []
    max_s = max(scores)
    exp_scores = [math.exp((s - max_s) / temperature) for s in scores]
    sum_exp = sum(exp_scores)
    if sum_exp == 0:
        return [1.0 / len(scores)] * len(scores)
    return [s / sum_exp for s in exp_scores]


# ---------------------------------------------------------------------------
# JevRouter Implementation
# ---------------------------------------------------------------------------


class JevRouter:
    """Non-autoregressive System-1 semantic router with sub-35ms latency guarantee.

    Coordinates safety gating (Noul), complexity scoring (Score), and discrete candidate
    routing (Choice). Integrates with remote Jev API if configured, with a sub-10ms
    deterministic local semantic classifier fallback.
    """

    DEFAULT_TIMEOUT_S: ClassVar[float] = 0.030  # 30ms

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http_client: Any = None,
        fallback_on_error: bool = True,
    ) -> None:
        self.endpoint: str | None = endpoint or os.environ.get("JEV_ENDPOINT")
        self.timeout_s: float = timeout_s
        self.http_client: Any = http_client
        self.fallback_on_error: bool = fallback_on_error

        if api_key is not None:
            self.api_key: str | None = api_key
        else:
            self.api_key = self._resolve_api_key()

    def _resolve_api_key(self) -> str | None:
        """Resolve ``JEV_API_KEY``; fall back to ``OPENROUTER_API_KEY`` for OpenRouter endpoints.

        The OpenRouter key is only ever offered to ``openrouter.ai`` itself, so a
        misconfigured ``JEV_ENDPOINT`` cannot receive it.
        """
        try:
            from swarm_sdk.vault import get_jev_key, resolve

            key = get_jev_key()
            if key:
                return key
            if self._endpoint_is_openrouter():
                key = resolve("OPENROUTER_API_KEY")
                if key:
                    return key
        except Exception:
            pass
        return os.environ.get("JEV_API_KEY")

    def _endpoint_is_openrouter(self) -> bool:
        host = urlparse(self.endpoint or "").hostname or ""
        return host == "openrouter.ai" or host.endswith(".openrouter.ai")

    def _post_remote(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Attempts remote POST to Jev microservice with timeout guard."""
        if not self.endpoint or not self.api_key:
            return None

        url = f"{self.endpoint.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # 1. Custom or mocked HTTP client
        if self.http_client is not None:
            resp = self.http_client.post(url, json=payload, headers=headers, timeout=self.timeout_s)
            if hasattr(resp, "status_code") and resp.status_code == 200:
                if hasattr(resp, "json"):
                    return resp.json()
            elif hasattr(resp, "status") and resp.status == 200:
                if hasattr(resp, "json"):
                    return resp.json()
            return None

        # 2. Standard library fallback
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
            if response.status == 200:
                body = response.read().decode("utf-8")
                return json.loads(body)

        return None

    # -----------------------------------------------------------------------
    # Noul Decision
    # -----------------------------------------------------------------------

    def evaluate_noul(self, task: str, context: str = "") -> NoulDecision:
        """Evaluates whether a task is safe to execute or blocked due to unsafe traits."""
        t0 = time.perf_counter()

        if self.endpoint and self.api_key:
            try:
                remote_data = self._post_remote("evaluate/noul", {"task": task, "context": context})
                if remote_data is not None and "decision" in remote_data:
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    remote_data.setdefault("latency_ms", round(elapsed_ms, 3))
                    return NoulDecision(**remote_data)
            except Exception as exc:
                logger.debug("Remote Jev evaluate_noul failed (%s); triggering local fallback", exc)
                if not self.fallback_on_error:
                    raise

        return self._local_evaluate_noul(task, context, start_time=t0)

    def _local_evaluate_noul(
        self, task: str, context: str = "", start_time: float | None = None
    ) -> NoulDecision:
        t0 = start_time if start_time is not None else time.perf_counter()
        full_text = f"{task}\n{context}".strip()

        # 1. Destructive commands
        if (
            _RE_DESTRUCTIVE_RM.search(full_text)
            or _RE_FORK_BOMB.search(full_text)
            or _RE_DISK_CORRUPT.search(full_text)
        ):
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return NoulDecision(
                decision=False,
                confidence=0.99,
                reasoning_tag="unsafe_destructive_command",
                latency_ms=round(elapsed_ms, 3),
            )

        # 2. Pipe to shell
        if _RE_PIPE_TO_SHELL.search(full_text):
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return NoulDecision(
                decision=False,
                confidence=0.98,
                reasoning_tag="unsafe_pipe_to_shell",
                latency_ms=round(elapsed_ms, 3),
            )

        # 3. Secret exfiltration
        if _RE_SECRET_EXFILTRATION.search(full_text):
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return NoulDecision(
                decision=False,
                confidence=0.98,
                reasoning_tag="unsafe_secret_exfiltration",
                latency_ms=round(elapsed_ms, 3),
            )

        # 4. Malicious operations / reverse shells
        if _RE_MALICIOUS_OPS.search(full_text):
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return NoulDecision(
                decision=False,
                confidence=0.99,
                reasoning_tag="unsafe_malicious_operation",
                latency_ms=round(elapsed_ms, 3),
            )

        # Safe pass
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return NoulDecision(
            decision=True,
            confidence=0.95,
            reasoning_tag="safe_pass",
            latency_ms=round(elapsed_ms, 3),
        )

    # -----------------------------------------------------------------------
    # Score Decision
    # -----------------------------------------------------------------------

    def evaluate_score(self, task: str, context: str = "") -> ScoreDecision:
        """Evaluates task complexity and selects optimal model tier (flash_lite, flash, pro)."""
        t0 = time.perf_counter()

        if self.endpoint and self.api_key:
            try:
                remote_data = self._post_remote(
                    "evaluate/score", {"task": task, "context": context}
                )
                if remote_data is not None and "score" in remote_data:
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    remote_data.setdefault("latency_ms", round(elapsed_ms, 3))
                    return ScoreDecision(**remote_data)
            except Exception as exc:
                logger.debug(
                    "Remote Jev evaluate_score failed (%s); triggering local fallback", exc
                )
                if not self.fallback_on_error:
                    raise

        return self._local_evaluate_score(task, context, start_time=t0)

    def _local_evaluate_score(
        self, task: str, context: str = "", start_time: float | None = None
    ) -> ScoreDecision:
        t0 = start_time if start_time is not None else time.perf_counter()
        full_text = f"{task}\n{context}".strip()

        # Check Pro indicators
        pro_matches = 0
        if _RE_PRO_MULTI_FILE.search(full_text):
            pro_matches += 2
        if _RE_PRO_ARCHITECTURE.search(full_text):
            pro_matches += 2
        if _RE_PRO_CONCURRENCY.search(full_text):
            pro_matches += 2
        if _RE_PRO_LOW_LEVEL.search(full_text):
            pro_matches += 2
        if _RE_PRO_DISTRIBUTED.search(full_text):
            pro_matches += 2

        if pro_matches > 0:
            score = min(0.95, 0.78 + (pro_matches * 0.03))
            model_tier = "pro"
            complexity_bucket = "high"
        else:
            # Check Low / Flash-Lite indicators
            low_matches = 0
            if _RE_LOW_TYPO.search(full_text):
                low_matches += 1
            if _RE_LOW_DOCS.search(full_text):
                low_matches += 1
            if _RE_LOW_FORMAT.search(full_text):
                low_matches += 1
            if _RE_LOW_LOOKUP.search(full_text):
                low_matches += 1

            if low_matches > 0:
                score = max(0.12, 0.30 - (low_matches * 0.05))
                model_tier = "flash_lite"
                complexity_bucket = "low"
            else:
                # Medium / Flash baseline
                score = 0.55
                model_tier = "flash"
                complexity_bucket = "medium"

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ScoreDecision(
            score=round(score, 3),
            model_tier=model_tier,
            complexity_bucket=complexity_bucket,
            latency_ms=round(elapsed_ms, 3),
        )

    # -----------------------------------------------------------------------
    # Choice Decision
    # -----------------------------------------------------------------------

    def evaluate_choice(
        self, task: str, candidates: list[str], context: str = ""
    ) -> ChoiceDecision:
        """Selects the optimal candidate option from candidates."""
        if not candidates:
            raise ValueError("candidates list cannot be empty")

        t0 = time.perf_counter()

        if self.endpoint and self.api_key:
            try:
                remote_data = self._post_remote(
                    "evaluate/choice",
                    {"task": task, "candidates": candidates, "context": context},
                )
                if remote_data is not None and "selected_choice" in remote_data:
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    remote_data.setdefault("latency_ms", round(elapsed_ms, 3))
                    return ChoiceDecision(**remote_data)
            except Exception as exc:
                logger.debug(
                    "Remote Jev evaluate_choice failed (%s); triggering local fallback", exc
                )
                if not self.fallback_on_error:
                    raise

        return self._local_evaluate_choice(task, candidates, context, start_time=t0)

    def _local_evaluate_choice(
        self,
        task: str,
        candidates: list[str],
        context: str = "",
        start_time: float | None = None,
    ) -> ChoiceDecision:
        t0 = start_time if start_time is not None else time.perf_counter()
        full_text = f"{task}\n{context}".lower()

        scores: list[float] = []
        for candidate in candidates:
            cand_key = candidate.lower()
            score = 1.0  # Base prior

            # Direct name match in text
            if cand_key in full_text:
                score += 3.0

            # Match semantic keywords associated with candidate
            keywords = _CANDIDATE_KEYWORDS.get(cand_key, [])
            for kw in keywords:
                if kw in full_text:
                    score += 2.0

            scores.append(score)

        probs = _softmax(scores, temperature=1.0)
        best_idx = max(range(len(candidates)), key=lambda i: probs[i])
        selected_choice = candidates[best_idx]

        probabilities: dict[str, float] = {}
        for cand, p in zip(candidates, probs):
            probabilities[cand] = round(p, 4)

        # Re-balance small rounding diff on selected choice so probabilities sum to 1.0
        diff = round(1.0 - sum(probabilities.values()), 4)
        probabilities[selected_choice] = round(probabilities[selected_choice] + diff, 4)
        confidence = probabilities[selected_choice]

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ChoiceDecision(
            selected_choice=selected_choice,
            confidence=confidence,
            probabilities=probabilities,
            latency_ms=round(elapsed_ms, 3),
        )
