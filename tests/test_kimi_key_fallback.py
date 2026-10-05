"""Moonshot keeps the primary Kimi key, then uses the fallback after HTTP 401."""

import asyncio
import os

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from swarm_sdk.agents.manifest import AgentManifest
from swarm_sdk.models import chat
from swarm_sdk.orchestrator.worker import WorkerAgent


class _Auth(Exception):
    """Provider rejection that exposes an HTTP status and no secret."""

    status_code = 401


class _Reply:
    """Enough of a chat result for ``message_text``."""

    content = "pong"
    usage_metadata = {"total_tokens": 1}


class _Scripted(BaseChatModel):
    """Accepts only the fixture fallback token."""

    token: str = ""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        raise NotImplementedError

    def invoke(self, input: object, config: object = None, **kwargs: object) -> _Reply:
        """Reject the primary fixture token once, then answer."""
        if self.token == "primary":
            raise _Auth("unauthorized")
        return _Reply()


def _label(value: object) -> str:
    """Map a fixture token to a name. Any other value stays unlabeled."""
    if value == "primary":
        return "primary"
    if value == "fallback":
        return "fallback"
    return "other"


def test_moonshot_401_uses_the_kimi_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401 from the primary Kimi key rebuilds the client with the fallback."""
    for name in (
        "KIMI_API_KEY",
        "KIMI_API_KEY_DUPLICATE_1",
        "KIMI_CODE_PLAN_API_KEY",
        "MOONSHOT_API_KEY",
        "MOONSHOT_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        chat.vault,
        "get",
        lambda name: {
            "KIMI_API_KEY": "primary",
            "KIMI_API_KEY_DUPLICATE_1": "fallback",
        }.get(name),
    )
    calls: list[object] = []

    def _init(model: str, **kwargs: object) -> _Scripted:
        calls.append(kwargs.get("api_key"))
        return _Scripted(token=str(kwargs.get("api_key") or ""))

    chat.load_chat_model_cache_clear()
    monkeypatch.setattr("langchain.chat_models.init_chat_model", _init)
    model = chat.load_chat_model("moonshot:kimi-k2.7-code")
    text, tokens = asyncio.run(chat.complete_with_usage(model, "sys", "ping"))
    assert text == "pong"
    assert tokens == 1
    assert [_label(item) for item in calls] == ["primary", "fallback"]
    chat.load_chat_model("moonshot:kimi-k2.7-code")
    assert [_label(item) for item in calls] == ["primary", "fallback"]


def test_worker_accepts_the_kimi_fallback_when_the_primary_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Math-style manifests can run when only KIMI_API_KEY_DUPLICATE_1 is stored."""
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.setattr(
        "swarm_sdk.vault.get",
        lambda name: "fallback" if name == "KIMI_API_KEY_DUPLICATE_1" else None,
    )
    manifest = AgentManifest(
        name="math",
        role="mathematical_modeling",
        model="moonshot:kimi-k2.7-code",
        api_key_env="KIMI_API_KEY",
    )
    worker = WorkerAgent(manifest, agents_root=".")
    try:
        worker._resolve_api_key()
        selected = os.environ.get("MOONSHOT_API_KEY")
    finally:
        os.environ.pop("MOONSHOT_API_KEY", None)
    assert _label(selected) == "fallback"
