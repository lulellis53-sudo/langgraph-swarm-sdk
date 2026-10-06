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
    # Never read the real Keychain from a test: a failing assertion would print the secret.
    monkeypatch.setattr(chat.vault, "get", lambda *args, **kwargs: None)
    # Earlier tests may have primed real keys into os.environ; a route test must start clean.
    for key_env, base_env in chat._route_index().values():
        monkeypatch.delenv(key_env, raising=False)
        monkeypatch.delenv(base_env, raising=False)
    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        lambda model, **kwargs: calls.append((model, kwargs)) or _Dummy(),
    )
    monkeypatch.setattr("langchain_core.language_models.chat_models.BaseChatModel", _Dummy)
    return calls


def test_google_prefix_routes_to_google_genai(fake_init) -> None:
    chat.load_chat_model("google:gemini-3.8-flash")
    assert fake_init == [("google_genai:gemini-3.8-flash", {})]


def test_compat_provider_uses_registry_base_url(fake_init, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    monkeypatch.setenv("ZAI_API_KEY", "k")
    chat.load_chat_model("zai:glm-5.2")
    ((model, kwargs),) = fake_init
    assert model == "glm-5.2"
    assert kwargs["model_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.z.ai/api/paas/v4"
    assert kwargs["api_key"] == "k"


def test_compat_provider_requires_base_url(fake_init, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="MINIMAX_BASE_URL"):
        chat.load_chat_model("minimax:minimax-2.7-high-speed")
    assert fake_init == []


def test_mistral_prefix_routes_to_the_mistralai_provider(
    fake_init, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY_1", "mk")
    chat.load_chat_model("mistral:mistral-large-latest")
    ((model, kwargs),) = fake_init
    assert model == "mistral-large-latest"  # the ``mistral:`` prefix is not sent to the API
    assert kwargs == {"model_provider": "mistralai", "mistral_api_key": "mk"}


def test_compat_base_url_falls_back_to_the_vault(
    fake_init, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    seen: list[str] = []

    def fake_get(name: str, **kwargs: object) -> str | None:
        seen.append(name)
        return "https://api.minimax.example/v1" if name == "MINIMAX_BASE_URL" else None

    monkeypatch.setattr(chat.vault, "get", fake_get)
    chat.load_chat_model("minimax:minimax-2.7-high-speed")
    ((_, kwargs),) = fake_init
    assert kwargs["base_url"] == "https://api.minimax.example/v1"
    assert "MINIMAX_BASE_URL" in seen


def test_registry_cohere_and_fireworks_ids_match_the_provider_catalogues() -> None:
    names = set(chat._route_index())
    assert {"cohere:command-a-03-2025", "cohere:command-r7b-12-2024"} <= names
    assert "fireworks:accounts/fireworks/models/glm-5p3-flash" in names
