"""Registry-driven model routes: google rewrite and OpenAI-compatible providers."""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from swarm_sdk import vault
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


@pytest.mark.parametrize(
    ("route", "key_name", "base_url"),
    [
        ("openrouter:z-ai/glm-5.3-flash", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
        (
            "sambanova:Meta-Llama-3.3-70B-Instruct",
            "SAMBANOVA_API_KEY",
            "https://api.sambanova.ai/v1",
        ),
        (
            "fireworks:accounts/fireworks/models/kimi-k2.7",
            "FIREWORKS_API_KEY",
            "https://api.fireworks.ai/inference/v1",
        ),
    ],
)
def test_hosted_compat_routes_use_provider_endpoint(
    fake_init, monkeypatch: pytest.MonkeyPatch, route: str, key_name: str, base_url: str
) -> None:
    monkeypatch.setenv(key_name, "synthetic-key")
    chat.load_chat_model(route)
    ((model, kwargs),) = fake_init
    assert model == route.split(":", 1)[1]
    assert kwargs == {"model_provider": "openai", "base_url": base_url, "api_key": "synthetic-key"}


def test_hosted_route_reads_named_key_from_vault(
    fake_init, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        vault, "get", lambda name: "vault-key" if name == "OPENROUTER_API_KEY" else None
    )
    chat.load_chat_model("openrouter:z-ai/glm-5.3-flash")
    assert fake_init[0][1]["api_key"] == "vault-key"


def test_google_route_reads_named_key_from_vault(
    fake_init, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        vault, "get", lambda name: "vault-key" if name == "GEMINI_API_KEY" else None
    )
    chat.load_chat_model("google:gemini-3.8-flash")
    assert fake_init == [("google_genai:gemini-3.8-flash", {"google_api_key": "vault-key"})]
