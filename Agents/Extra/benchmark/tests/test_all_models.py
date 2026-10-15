"""Offline route tests for every chat model in the packaged registry.

No network and no real credentials: ``init_chat_model`` is replaced by a recorder and each
route gets sentinel values, so the tests prove how a key reaches a provider, not that it works.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from swarm_sdk.models import chat

_REGISTRY = Path("src/swarm_sdk/agents/config/model_registry.yaml")
_ROUTES: list[dict] = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))["providers"]
_KEYED = [r for r in _ROUTES if r.get("api_key_env")]
_KEYLESS = [r for r in _ROUTES if not r.get("api_key_env")]
_NATIVE_KEY_KWARG = chat._KEY_KWARG


class _Dummy(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "dummy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _fresh_model_cache() -> Iterator[None]:
    """Build every model from scratch: a cache hit would skip the recorded init call."""
    chat.load_chat_model_cache_clear()
    yield
    chat.load_chat_model_cache_clear()


@pytest.fixture
def fake_init(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "langchain.chat_models.init_chat_model",
        lambda model, **kwargs: calls.append((model, kwargs)) or _Dummy(),
    )
    monkeypatch.setattr("langchain_core.language_models.chat_models.BaseChatModel", _Dummy)
    return calls


def _arm(route: dict, monkeypatch: pytest.MonkeyPatch) -> str:
    """Set the sentinel key and base URL a route needs; return the sentinel key."""
    sentinel = f"sentinel-{route['name']}"
    if route.get("api_key_env"):
        monkeypatch.setenv(route["api_key_env"], sentinel)
    if route.get("base_url_env"):
        monkeypatch.setenv(route["base_url_env"], "https://example.invalid/v1")
    return sentinel


def test_registry_has_unique_names_and_known_providers() -> None:
    names = [r["name"] for r in _ROUTES]
    assert len(names) == len(set(names))
    assert all(":" in name for name in names)
    assert len(_ROUTES) >= 25


@pytest.mark.parametrize("route", _ROUTES, ids=[r["name"] for r in _ROUTES])
def test_route_builds_exactly_one_model(
    route: dict, fake_init: list[tuple[str, dict]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _arm(route, monkeypatch)
    model = chat.load_chat_model(route["name"])
    assert isinstance(model, _Dummy)
    assert len(fake_init) == 1


@pytest.mark.parametrize("route", _KEYED, ids=[r["name"] for r in _KEYED])
def test_key_reaches_provider_under_the_right_kwarg(
    route: dict, fake_init: list[tuple[str, dict]], monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = _arm(route, monkeypatch)
    chat.load_chat_model(route["name"])
    ((_, kwargs),) = fake_init
    provider = route["name"].partition(":")[0]
    if provider in chat._COMPAT_PROVIDERS:
        assert kwargs["api_key"] == sentinel
        assert kwargs["model_provider"] == "openai"
        assert kwargs["base_url"]
    elif provider == "google":
        assert kwargs == {"google_api_key": sentinel}
    elif provider in _NATIVE_KEY_KWARG:
        assert kwargs[_NATIVE_KEY_KWARG[provider]] == sentinel
    else:
        # Providers without a known kwarg get no key passed explicitly.
        assert sentinel not in kwargs.values()


@pytest.mark.parametrize("route", _KEYED, ids=[r["name"] for r in _KEYED])
def test_missing_key_is_never_invented(
    route: dict, fake_init: list[tuple[str, dict]], monkeypatch: pytest.MonkeyPatch
) -> None:
    if route.get("base_url_env"):
        monkeypatch.setenv(route["base_url_env"], "https://example.invalid/v1")
    chat.load_chat_model(route["name"])
    ((_, kwargs),) = fake_init
    assert not {"google_api_key", "groq_api_key", "anthropic_api_key"} & kwargs.keys()
    assert not kwargs.get("api_key")


@pytest.mark.parametrize("route", _KEYLESS, ids=[r["name"] for r in _KEYLESS])
def test_keyless_routes_need_only_a_base_url(
    route: dict, fake_init: list[tuple[str, dict]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _arm(route, monkeypatch)
    chat.load_chat_model(route["name"])
    assert len(fake_init) == 1


def test_real_environment_cannot_leak_into_a_route(
    fake_init: list[tuple[str, dict]],
) -> None:
    """The autouse isolation fixture leaves no registry key resolvable."""
    chat.load_chat_model("google:gemini-3.8-flash")
    assert fake_init == [("google_genai:gemini-3.8-flash", {})]
