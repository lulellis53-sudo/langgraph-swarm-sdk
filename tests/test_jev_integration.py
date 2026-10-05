"""Tests for JEV System-1 routing integration with SwarmSDK."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from swarm_sdk.config.loader import SwarmFileConfig
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK


class TestJevSwarmSDKIntegration:
    """Verify JEV picks the entry agent deterministically inside SwarmSDK."""

    @pytest.fixture
    def sdk(self) -> SwarmSDK:
        """SwarmSDK with JEV enabled and heavy dependencies mocked."""
        settings = Settings(
            jev_routing=True,
            embed_backend="hash",
        )
        embedder = MagicMock()
        embedder.embed.return_value = [[0.0] * settings.embed_dim]
        return SwarmSDK(
            settings=settings,
            file_config=SwarmFileConfig(),
            embedder=embedder,
            reranker=MagicMock(),
            memory=MagicMock(),
            cache=MagicMock(),
        )

    def test_jev_routes_coding_prompt_to_coder(self, sdk: SwarmSDK) -> None:
        """A coding task with JEV enabled starts on the coder node."""
        with patch.object(
            sdk._jev,
            "evaluate_choice",
            return_value=MagicMock(selected_choice="coder", confidence=0.72),
        ) as mock_choice:
            agent = sdk._jev_default_agent("Implement a new API endpoint")
            mock_choice.assert_called_once()
            assert agent == "coder"

    def test_jev_routes_review_prompt_to_reviewer(self, sdk: SwarmSDK) -> None:
        """A review task with JEV enabled starts on the reviewer node."""
        with patch.object(
            sdk._jev,
            "evaluate_choice",
            return_value=MagicMock(selected_choice="reviewer", confidence=0.68),
        ):
            agent = sdk._jev_default_agent("Review the pull request diff")
            assert agent == "reviewer"

    def test_jev_disabled_uses_static_default(self) -> None:
        """When JEV routing is disabled the static default agent is used."""
        settings = Settings(jev_routing=False, embed_backend="hash")
        embedder = MagicMock()
        embedder.embed.return_value = [[0.0] * settings.embed_dim]
        sdk = SwarmSDK(
            settings=settings,
            file_config=SwarmFileConfig(),
            embedder=embedder,
            reranker=MagicMock(),
            memory=MagicMock(),
            cache=MagicMock(),
        )

        with patch.object(sdk._jev, "evaluate_choice") as mock_choice:
            agent = sdk._jev_default_agent("Implement a new API endpoint")
            mock_choice.assert_not_called()
            assert agent == sdk._default_agent

    def test_jev_unknown_choice_falls_back(self, sdk: SwarmSDK) -> None:
        """A JEV choice that is not a wired node falls back to the static default."""
        with patch.object(
            sdk._jev,
            "evaluate_choice",
            return_value=MagicMock(selected_choice="nonexistent", confidence=0.5),
        ):
            agent = sdk._jev_default_agent("Do something vague")
            assert agent == sdk._default_agent

    def test_jev_exception_falls_back(self, sdk: SwarmSDK) -> None:
        """An exception from JEV evaluation falls back to the static default."""
        with patch.object(sdk._jev, "evaluate_choice", side_effect=RuntimeError("JEV timeout")):
            agent = sdk._jev_default_agent("Do something")
            assert agent == sdk._default_agent

    @pytest.mark.asyncio
    async def test_swarm_passes_text_to_jev_for_new_thread(self, sdk: SwarmSDK) -> None:
        """_swarm asks JEV for the entry agent when starting a new thread."""
        packed = MagicMock()
        packed.user = "Implement a new feature"
        packed.system = "system"
        packed.text = "system\nImplement a new feature"

        graph = MagicMock()
        graph.invoke.return_value = {
            "messages": [{"role": "ai", "content": "done"}],
            "active_agent": "coder",
        }
        sdk._compiled = graph

        with patch.object(
            sdk._jev,
            "evaluate_choice",
            return_value=MagicMock(selected_choice="coder", confidence=0.72),
        ) as mock_choice:
            await sdk._swarm(packed, "Implement a new feature", "thread-jev-1")
            mock_choice.assert_called_once_with(
                "Implement a new feature",
                sorted(sdk._langgraph_manifests) or sorted(["researcher", "coder", "reviewer"]),
            )

    @pytest.mark.asyncio
    async def test_swarm_uses_static_default_for_existing_thread(self, sdk: SwarmSDK) -> None:
        """Existing threads reuse the checkpointer's active_agent; JEV is not consulted."""
        packed = MagicMock()
        packed.user = "Implement a new feature"
        packed.system = "system"
        packed.text = "system\nImplement a new feature"

        graph = MagicMock()
        graph.invoke.return_value = {
            "messages": [{"role": "ai", "content": "done"}],
            "active_agent": "reviewer",
        }
        sdk._compiled = graph

        # Pretend the thread already exists.
        with (
            patch.object(sdk, "_is_new_thread", return_value=False),
            patch.object(sdk._jev, "evaluate_choice") as mock_choice,
        ):
            await sdk._swarm(packed, "Implement a new feature", "thread-existing")
            mock_choice.assert_not_called()
