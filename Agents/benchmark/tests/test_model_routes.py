"""Registry-driven model routes: google rewrite and OpenAI-compatible providers."""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from swarm_sdk.models import chat


class _Dummy(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "dummy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        raise NotImplementedError


@pytest.fixture()
def fake_init(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        lambda model, **kwargs: calls.append((model, kwargs)) or _Dummy(),
    )
    monkeypatch.setattr(
        "langchain_core.language_models.chat_models.BaseChatModel", _Dummy
    )
    return calls


def test_google_prefix_routes_to_google_genai(fake_init) -> None:
    chat.load_chat_model("google:gemini-3.8-flash")
    assert fake_init == [("google_genai:gemini-3.8-flash", {})]


def test_compat_provider_uses_registry_base_url(
    fake_init, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    monkeypatch.setenv("ZAI_API_KEY", "k")
    chat.load_chat_model("zai:glm-5.2")
    (model, kwargs), = fake_init
    assert model == "glm-5.2"
    assert kwargs["model_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.z.ai/api/paas/v4"
    assert kwargs["api_key"] == "k"


def test_compat_provider_requires_base_url(
    fake_init, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="MINIMAX_BASE_URL"):
        chat.load_chat_model("minimax:minimax-2.7-high-speed")
    assert fake_init == []
