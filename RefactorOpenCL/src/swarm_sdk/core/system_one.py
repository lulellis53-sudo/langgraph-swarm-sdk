"""Hosted TypeSafe System One hint for plan routing.

One POST to ``/v1/systemone`` sends the goal as state and asks Noul, Score,
and Choice together. The returned model id is kept. A missing key, a timeout,
or an HTTP error abstains. The numbers are evidence for the planner. They are
not a calibrated gate and they do not authorize a write.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
_TIMEOUT_S = 2.0
_MAX_RETRY_WAIT_S = 1.0
_CHOICE_LIMIT = 255

Post = Callable[[dict[str, Any], str], dict[str, Any]]
Sleep = Callable[[float], None]

_ABSTAIN = (
    "JEV abstained: {reason}. Use the routing table. "
    "A publish, delete, or production write still waits for a person."
)
_HINT = (
    "JEV model={model} noul={noul} score={score} choice={choice} "
    "confidence={confidence}. These values are not a calibrated gate and are "
    "not proof. A publish, delete, or production write still waits for a person. "
    "If choice is abstained, use the routing table."
)


class SystemOneHTTPError(Exception):
    """HTTP status from the System One endpoint."""

    def __init__(self, status: int, retry_after: float | None) -> None:
        """Record the status and a parsed Retry-After, if the header was usable."""
        super().__init__(f"system one HTTP {status}")
        self.status = status
        self.retry_after = retry_after


def post_system_one(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    """POST one System One request. Does not retry.

    Args:
        payload: JSON body with state, model, and questions.
        api_key: Bearer token. It is not included in any raised message.

    Returns:
        The decoded JSON object.

    Raises:
        SystemOneHTTPError: On a non-200 response.
        TimeoutError: When the socket times out.
        urllib.error.URLError: On a transport failure other than HTTP status.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        SYSTEMONE_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        header = exc.headers.get("Retry-After") if exc.headers else None
        raise SystemOneHTTPError(exc.code, _retry_after(header)) from exc
    if not isinstance(body, dict):
        raise SystemOneHTTPError(200, None)
    return body


def jev_advice(
    goal: str,
    candidates: list[str],
    *,
    post: Post | None = None,
    sleep: Sleep = time.sleep,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Ask hosted Jev about one goal, or abstain.

    Args:
        goal: Text state. This is the only content sent.
        candidates: Agent names for the Choice question, in tie-break order.
        post: Transport. The default is :func:`post_system_one`.
        sleep: Wait used for one rate-limit retry.
        environ: Key source. Defaults to ``os.environ``.

    Returns:
        A one-paragraph hint. Never includes the API key.
    """
    env = os.environ if environ is None else environ
    key = _jev_key(env)
    if not key:
        return _ABSTAIN.format(reason="no TYPESAFE_API_KEY or JEV_API_KEY")
    state = goal.strip()
    if not state:
        return _ABSTAIN.format(reason="empty state")
    names = _names(candidates)
    payload = {
        "state": state,
        "model": env.get("JEV_MODEL") or DEFAULT_MODEL,
        "questions": _questions(names),
    }
    send = post or post_system_one
    try:
        body = _call(send, payload, key, sleep)
    except SystemOneHTTPError as exc:
        return _ABSTAIN.format(reason=f"HTTP {exc.status}")
    except TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError:
        return _ABSTAIN.format(reason="unavailable")
    return _format(body, names)


def _jev_key(env: Mapping[str, str]) -> str:
    """Return the Jev bearer token. An explicit mapping does not read the vault.

    Args:
        env: Key source. The process environment may fall back to the vault.

    Returns:
        The token, or an empty string when none is available. The value is not logged.
    """
    key = env.get("TYPESAFE_API_KEY") or env.get("JEV_API_KEY") or ""
    if key or env is not os.environ:
        return key
    try:
        from swarm_sdk.vault import VaultError, get_jev_key
    except ImportError:
        return ""
    try:
        return get_jev_key() or ""
    except VaultError, OSError:
        return ""


def _names(candidates: list[str]) -> list[str]:
    seen: list[str] = []
    for name in candidates:
        text = name.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _questions(names: list[str]) -> dict[str, Any]:
    questions: dict[str, Any] = {
        "route_ready": {
            "type": "noul",
            "instructions": "Is the goal specific enough to assign without asking a person?",
            "criteria": {
                "true": "The outcome and the done check are stated.",
                "false": "The goal is missing, contradictory, or needs a person first.",
            },
        },
        "depth": {
            "type": "score",
            "instructions": "How deep a plan does this goal need?",
            "criteria": [
                "One direct step with a known check.",
                "A short chain with a check between stages.",
                "A specialist path with several owners.",
            ],
        },
    }
    if 0 < len(names) <= _CHOICE_LIMIT:
        questions["owner"] = {
            "type": "choice",
            "instructions": "Which named agent should own the first step?",
            "criteria": dict.fromkeys(names),
        }
    return questions


def _call(post: Post, payload: dict[str, Any], key: str, sleep: Sleep) -> dict[str, Any]:
    try:
        return post(payload, key)
    except SystemOneHTTPError as exc:
        if exc.status not in (429, 529):
            raise
        delay = 0.2 if exc.retry_after is None else exc.retry_after
        if delay > _MAX_RETRY_WAIT_S:
            raise
        sleep(delay)
        return post(payload, key)


def _format(body: dict[str, Any], names: list[str]) -> str:
    model = body.get("model")
    answers = body.get("answers")
    if not isinstance(model, str) or not model or not isinstance(answers, dict):
        return _ABSTAIN.format(reason="malformed response")
    noul = _noul(answers.get("route_ready"))
    score = _score(answers.get("depth"))
    choice, confidence = _choice(answers.get("owner"), names)
    return _HINT.format(
        model=model,
        noul=noul,
        score=score,
        choice=choice,
        confidence=confidence,
    )


def _noul(answer: object) -> str:
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        return "abstained"
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "abstained"
    return f"{float(value):.3f}"


def _score(answer: object) -> str:
    if not isinstance(answer, dict) or answer.get("type") != "score":
        return "abstained"
    value = answer.get("score")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "abstained"
    return f"{float(value):.3f}"


def _choice(answer: object, names: list[str]) -> tuple[str, str]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return "abstained", "absent"
    selected = answer.get("choice")
    if not isinstance(selected, str) or selected not in names:
        return "abstained", "absent"
    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return selected, "absent"
    return selected, f"{float(confidence):.3f}"


def _retry_after(header: str | None) -> float | None:
    if header is None:
        return None
    try:
        return float(header.strip())
    except ValueError:
        return None
