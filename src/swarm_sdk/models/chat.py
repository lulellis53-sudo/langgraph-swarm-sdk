"""Chat-model helpers."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import yaml

from swarm_sdk import vault
from swarm_sdk.execution.executor import offload
from swarm_sdk.prompting.budget import count_text

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


def message_text(message: object) -> str:
    """Extract plain text from a chat message or dict payload.

    Args:
        message: LangChain message, dict with ``content``, or other object.

    Returns:
        Concatenated text content, or ``str(message)`` as a last resort.
    """
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content)


class Route(NamedTuple):
    """One registry row. ``model_id`` overrides the name suffix when a second key aliases it."""

    api_key_env: str
    base_url_env: str
    model_id: str = ""
    key_fallbacks: tuple[str, ...] = ()


def _name_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if isinstance(item, str) and (text := item.strip()))


@lru_cache(maxsize=1)
def _route_index() -> dict[str, Route]:
    """Model name -> route from the packaged registry."""
    path = Path(__file__).resolve().parent.parent / "agents" / "config" / "model_registry.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    index: dict[str, Route] = {}
    for entry in data.get("providers") or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            index[entry["name"]] = Route(
                entry.get("api_key_env") or "",
                entry.get("base_url_env") or "",
                entry.get("model_id") or "",
                _name_list(entry.get("api_key_fallbacks")),
            )
    return index


# OpenAI-compatible providers: their routes carry a ``base_url_env`` in the
# registry instead of a native LangChain integration.
_COMPAT_PROVIDERS = frozenset(
    {"zai", "minimax", "moonshot", "xiaomi", "nvidia", "openrouter", "sambanova", "fireworks"}
)
# Public OpenAI-compatible hosts. A vault or env base URL still wins.
_DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "sambanova": "https://api.sambanova.ai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "zai": "https://api.z.ai/api/paas/v4",
    "minimax": "https://api.minimax.io/v1",
    "moonshot": "https://api.moonshot.ai/v1",
}

_KEY_KWARG = {
    "openai": "api_key",
    "anthropic": "anthropic_api_key",
    "cohere": "cohere_api_key",
    "groq": "groq_api_key",
    "mistral": "mistral_api_key",
    "google_genai": "google_api_key",
    "xai": "xai_api_key",
}


def _present(name: str) -> bool:
    """True when ``name`` is set. The value is not returned."""
    if not name:
        return False
    if os.environ.get(name):
        return True
    try:
        return vault.get(name) is not None
    except vault.VaultError, OSError:
        return False


def _value(name: str) -> str:
    """Secret or base URL for ``name``. Callers must not log the result."""
    if not name:
        return ""
    return os.environ.get(name, "") or vault.get(name) or ""


def _first_value(names: tuple[str, ...]) -> str:
    for name in names:
        if found := _value(name):
            return found
    return ""


def _base_url(provider: str, route: Route) -> str:
    configured = _value(route.base_url_env).strip() if route.base_url_env else ""
    return configured or _DEFAULT_BASE_URLS.get(provider, "")


def route_is_ready(model_name: str) -> bool:
    """True when the route's key and, for hosted endpoints, a base URL are present.

    Presence only. Secret values are not returned.
    """
    provider, _, _ = model_name.partition(":")
    route = _route_index().get(model_name)
    if route is None:
        return False
    names = (route.api_key_env, *route.key_fallbacks)
    if route.api_key_env and not any(_present(name) for name in names):
        return False
    if provider in _COMPAT_PROVIDERS and not _base_url(provider, route):
        return False
    return True


def load_chat_model(model_name: str) -> BaseChatModel:
    """Initialize a LangChain chat model from a provider:name string.

    OpenAI-compatible providers (including ``zai``, ``openrouter``,
    ``sambanova`` and ``fireworks``) are constructed as ``ChatOpenAI``.
    Their base URL comes from the registry env name or a documented public
    default for hosted endpoints; ``google:`` routes to ``google_genai``.

    Args:
        model_name: e.g. ``"openai:gpt-4o-mini"`` or ``"zai:glm-5.3"``.

    Returns:
        A ``BaseChatModel`` instance.

    Raises:
        TypeError: If ``init_chat_model`` does not return a chat model.
        ValueError: If an OpenAI-compatible route has no base URL configured.
    """
    from langchain.chat_models import init_chat_model
    from langchain_core.language_models.chat_models import BaseChatModel

    provider, _, suffix = model_name.partition(":")
    route = _route_index().get(model_name, Route("", ""))
    model = route.model_id or suffix
    key_value = _first_value((route.api_key_env, *route.key_fallbacks))
    if provider == "google":
        kwargs = {"google_api_key": key_value} if key_value else {}
        chat_model = init_chat_model(f"google_genai:{model}", **kwargs)
    elif provider == "groq":
        kwargs = {"groq_api_key": key_value} if key_value else {}
        chat_model = init_chat_model(model, model_provider="groq", **kwargs)
    elif provider in _COMPAT_PROVIDERS:
        base_url = _base_url(provider, route)
        if not base_url:
            raise ValueError(
                f"{provider} routes need {route.base_url_env or 'a base URL env'} "
                "(OpenAI-compatible endpoint); store it with `swarm-vault set`"
            )
        chat_model = init_chat_model(
            model,
            model_provider="openai",
            base_url=base_url,
            api_key=key_value,
        )
    else:
        kwargs: dict[str, object] = {}
        key_kwarg = _KEY_KWARG.get(provider)
        if key_value and key_kwarg:
            kwargs[key_kwarg] = key_value
        # kwargs dict cannot match init_chat_model's static overloads;
        # the shapes are covered by test_model_routes.py.
        chat_model = init_chat_model(model_name, **kwargs)  # ty: ignore[no-matching-overload]
    if not isinstance(chat_model, BaseChatModel):
        raise TypeError(f"expected a chat model, got {type(chat_model).__name__}")
    return chat_model


def message_tokens(message: object) -> int | None:
    """Return the provider-reported token total for one message, if any."""
    if isinstance(message, dict):
        meta = message.get("usage_metadata")
    else:
        meta = getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    total = meta.get("total_tokens")
    if isinstance(total, int):
        return total
    prompt, reply = meta.get("input_tokens"), meta.get("output_tokens")
    if isinstance(prompt, int) and isinstance(reply, int):
        return prompt + reply
    return None


def _message_kind(message: object) -> object:
    if isinstance(message, dict):
        return message.get("role") or message.get("type")
    return getattr(message, "type", None)


def usage_tokens(messages: list[object]) -> int | None:
    """Sum provider token totals for AI messages after the last human message.

    Earlier turns are replayed by the checkpointer; counting them would double-charge.
    Returns ``None`` when no message reports usage.
    """
    start = 0
    for index, message in enumerate(messages):
        if _message_kind(message) in {"human", "user"}:
            start = index + 1
    reported = [t for m in messages[start:] if (t := message_tokens(m)) is not None]
    return sum(reported) if reported else None


async def complete_with_usage(
    model: BaseChatModel,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
) -> tuple[str, int]:
    """Invoke ``model`` on a system+user pair and return ``(text, tokens)``.

    Args:
        model: Chat model to call.
        system: System prompt.
        user: User / packed prompt body.
        json_mode: Ask the provider for a JSON object; retried once without it if the
            provider rejects ``response_format``.

    Returns:
        The reply text and the provider-reported token total, or an estimate
        (``count_text`` of system, user and reply) when the provider reports none.
    """

    def _call() -> tuple[str, int]:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        result = None
        if json_mode:
            try:
                result = model.bind(response_format={"type": "json_object"}).invoke(messages)
            except Exception:
                logger.warning("provider rejected response_format; retrying without it")
        if result is None:
            result = model.invoke(messages)
        text = message_text(result)
        reported = message_tokens(result)
        if reported is None:
            reported = count_text(system) + count_text(user) + count_text(text)
        return text, reported

    return await offload(_call)


async def complete(model: BaseChatModel, system: str, user: str) -> str:
    """Invoke ``model`` on a system+user pair via the shared thread pool.

    Args:
        model: Chat model to call.
        system: System prompt.
        user: User / packed prompt body.

    Returns:
        Model reply text.
    """
    text, _ = await complete_with_usage(model, system, user)
    return text


def last_ai_text(messages: list[object]) -> str:
    """Return the last assistant/AI message text from a transcript.

    Args:
        messages: Chronological message list (dicts or LangChain messages).

    Returns:
        Last AI/assistant text, or the last message's text, or ``""``.
    """
    for message in reversed(messages):
        if isinstance(message, dict):
            kind = message.get("role") or message.get("type")
        else:
            kind = getattr(message, "type", None)
        if kind in {"ai", "assistant"}:
            text = message_text(message)
            if text:
                return text
    if not messages:
        return ""
    return message_text(messages[-1])


__all__ = [
    "complete",
    "complete_with_usage",
    "last_ai_text",
    "load_chat_model",
    "message_text",
    "message_tokens",
    "usage_tokens",
]
