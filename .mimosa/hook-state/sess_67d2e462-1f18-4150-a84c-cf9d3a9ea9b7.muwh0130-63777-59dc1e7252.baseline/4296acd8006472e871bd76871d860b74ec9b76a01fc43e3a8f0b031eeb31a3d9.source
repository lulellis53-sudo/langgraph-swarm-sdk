"""Hosted System One hints: abstain, parse, and one bounded rate-limit retry."""

from __future__ import annotations

from swarm_sdk.core.system_one import SystemOneHTTPError, jev_advice

_HOSTED = {
    "model": "jev-1.13.0",
    "answers": {
        "route_ready": {"type": "noul", "noul": 0.91},
        "depth": {"type": "score", "score": 1.2, "confidence": 0.4},
        "owner": {
            "type": "choice",
            "choice": "Tester",
            "probabilities": {"Coder": 0.2, "Tester": 0.8},
            "confidence": 0.44,
        },
    },
    "usage": {"input_tokens": 10, "output_tokens": 4},
}


def test_missing_key_abstains_without_calling() -> None:
    """No API key means no request."""

    def post(payload: dict[str, object], api_key: str) -> dict[str, object]:
        raise AssertionError(payload)

    brief = jev_advice("fix a typo", ["Coder"], post=post, environ={})
    assert "JEV abstained" in brief
    assert "no TYPESAFE_API_KEY" in brief
    assert api_key_absent(brief)


def test_hosted_answer_keeps_model_and_raw_values() -> None:
    """A valid response is quoted. The choice must be one of the candidates."""
    seen: list[tuple[dict[str, object], str]] = []

    def post(payload: dict[str, object], api_key: str) -> dict[str, object]:
        seen.append((payload, api_key))
        return _HOSTED

    brief = jev_advice(
        "ask the tester to run pytest",
        ["Coder", "Tester"],
        post=post,
        environ={"TYPESAFE_API_KEY": "secret-token"},
    )
    assert seen[0][1] == "secret-token"
    assert seen[0][0]["model"] == "jev-latest"
    questions = seen[0][0]["questions"]
    assert isinstance(questions, dict)
    assert set(questions) == {"route_ready", "depth", "owner"}
    assert "model=jev-1.13.0" in brief
    assert "noul=0.910" in brief
    assert "score=1.200" in brief
    assert "choice=Tester" in brief
    assert "confidence=0.440" in brief
    assert "secret-token" not in brief


def test_unknown_choice_abstains_that_field() -> None:
    """An option outside the candidate list is not a routing decision."""
    body = {
        "model": "jev-1.13.0",
        "answers": {
            "route_ready": {"type": "noul", "noul": 0.2},
            "depth": {"type": "score", "score": 0.0},
            "owner": {"type": "choice", "choice": "Reviewer", "confidence": 0.99},
        },
    }
    brief = jev_advice("review", ["Coder"], post=lambda _p, _k: body, environ={"JEV_API_KEY": "k"})
    assert "choice=abstained" in brief
    assert "confidence=absent" in brief


def test_rate_limit_retries_once_inside_the_wait_cap() -> None:
    """429 with a short Retry-After is tried once. A long wait abstains."""
    calls = {"n": 0}

    def post(payload: dict[str, object], api_key: str) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemOneHTTPError(429, 0.0)
        return _HOSTED

    waited: list[float] = []
    brief = jev_advice(
        "goal",
        ["Tester"],
        post=post,
        sleep=waited.append,
        environ={"JEV_API_KEY": "k"},
    )
    assert calls["n"] == 2
    assert waited == [0.0]
    assert "model=jev-1.13.0" in brief

    def slow(payload: dict[str, object], api_key: str) -> dict[str, object]:
        raise SystemOneHTTPError(429, 30.0)

    brief = jev_advice(
        "goal", ["Tester"], post=slow, sleep=waited.append, environ={"JEV_API_KEY": "k"}
    )
    assert "HTTP 429" in brief
    assert waited == [0.0]


def test_unauthorized_does_not_retry() -> None:
    """401 is an abstention, not a second request."""
    calls = {"n": 0}

    def post(payload: dict[str, object], api_key: str) -> dict[str, object]:
        calls["n"] += 1
        raise SystemOneHTTPError(401, None)

    brief = jev_advice("goal", ["Coder"], post=post, environ={"JEV_API_KEY": "k"})
    assert calls["n"] == 1
    assert "HTTP 401" in brief


def api_key_absent(brief: str) -> bool:
    """The abstention text must not invent a token."""
    return "secret" not in brief
