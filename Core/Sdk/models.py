"""LangChain Chat Model Loader.

Initializes chat models across providers (OpenAI, Anthropic, Google, Groq, Mistral, Cerebras)
with structured configurations, timeout settings, and fallback chains.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


def load_chat_model(
    model: str = "gpt-4o",
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float = 60.0,
    **kwargs: Any,
) -> BaseChatModel:
    """Initialize a LangChain chat model.

    Uses `langchain.chat_models.init_chat_model` when available, with
    graceful provider resolution based on model prefix.

    Args:
        model: Model identifier (e.g. 'gpt-4o', 'anthropic:claude-3-5-sonnet',
            'google:gemini-1.5-pro', 'groq:llama-3.3-70b-versatile').
        temperature: Sampling temperature (0.0 for deterministic outputs).
        max_tokens: Optional upper bound on generated tokens.
        timeout: Request timeout in seconds.
        **kwargs: Additional provider-specific kwargs.

    Returns:
        Configured BaseChatModel instance.
    """
    try:
        from langchain.chat_models import init_chat_model

        # Extract provider prefix if specified as provider/model or provider:model
        provider: str | None = None
        clean_model = model
        if ":" in model:
            provider, clean_model = model.split(":", 1)
        elif "/" in model:
            provider, clean_model = model.split("/", 1)

        return init_chat_model(
            model=clean_model,
            model_provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
    except Exception as exc:
        logger.warning("init_chat_model failed for %s (%s); attempting fallback", model, exc)

    # Direct fallback to ChatOpenAI if init_chat_model cannot resolve provider
    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
    except ImportError:
        raise RuntimeError(
            f"Failed to load chat model '{model}'. Ensure the respective provider "
            "package (e.g. langchain-openai, langchain-anthropic) is installed."
        )


__all__ = ["load_chat_model"]
