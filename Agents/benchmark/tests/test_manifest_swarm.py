"""Manifest-driven handoff swarm: Agents/ personas become the LangGraph nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.agents.manifest import (
    AgentManifest,
    langgraph_manifests,
    load_all_agent_manifests,
)
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK, manifest_node_prompt
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


def _sdk(tmp_path: Path, model: ScriptedModel) -> SwarmSDK:
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
        memory_backend="opencl",
    )
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )


_MINIMAL_MANIFEST = """version: 1
name: Solo
role: solo_research
langgraph_node: researcher
model: openai:gpt-4o-mini
think_level: low
"""


def _solo_catalog(tmp_path: Path, *, contract: str | None = None) -> Path:
    """Create a one-agent catalog in ``tmp_path/Agents`` and return the dir."""
    agents = tmp_path / "Agents" / "Solo"
    agents.mkdir(parents=True)
    (agents / "agent.yaml").write_text(_MINIMAL_MANIFEST, encoding="utf-8")
    if contract is not None:
        (agents / "AGENTS.md").write_text(contract, encoding="utf-8")
    return tmp_path / "Agents"


def test_repo_manifests_wire_the_three_handoff_nodes() -> None:
    wired = langgraph_manifests(load_all_agent_manifests())
    assert set(wired) == {"researcher", "coder", "reviewer"}


def test_graph_nodes_follow_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _solo_catalog(tmp_path)
    sdk = _sdk(tmp_path, ScriptedModel(script=Script([answer("ok")])))

    nodes = set(cast(Any, sdk._graph()).nodes)

    assert "researcher" in nodes
    assert "coder" not in nodes
    assert "reviewer" not in nodes


def test_missing_catalog_falls_back_to_default_trio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    sdk = _sdk(tmp_path, ScriptedModel(script=Script([answer("ok")])))

    nodes = set(cast(Any, sdk._graph()).nodes)

    assert {"researcher", "coder", "reviewer"} <= nodes


def test_default_active_agent_follows_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _solo_catalog(tmp_path)
    sdk = _sdk(tmp_path, ScriptedModel(script=Script([answer("ok")])))

    assert sdk._default_agent == "researcher"


def test_node_prompt_prefers_role_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _solo_catalog(tmp_path, contract="# Agent: Solo\n\nPrecise single-agent contract.")
    manifest = load_all_agent_manifests(tmp_path / "Agents")["Solo"]

    prompt = manifest_node_prompt(str(tmp_path / "Agents"), manifest)

    assert "Precise single-agent contract." in prompt


def test_node_prompt_falls_back_to_manifest_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _solo_catalog(tmp_path)
    manifest = load_all_agent_manifests(tmp_path / "Agents")["Solo"]

    assert manifest_node_prompt(str(tmp_path / "Agents"), manifest) == "solo_research"


def test_node_prompt_of_promptless_node_uses_one_liner(tmp_path: Path) -> None:
    data = yaml.safe_load(_MINIMAL_MANIFEST)
    data["role"] = ""
    manifest = AgentManifest.model_validate(data)

    assert manifest_node_prompt(str(tmp_path / "Agents"), manifest).startswith(
        "You are the researcher."
    )


class _FakeSearchTool:
    """Minimal LangChain-style tool exposing only a ``name``."""

    name = "web_search_brief"


def _sdk_with_flag(tmp_path: Path, *, websearch: bool) -> SwarmSDK:
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=512,
        memory_backend="opencl",
        enable_websearch_tools=websearch,
    )
    model = ScriptedModel(script=Script([answer("ok")]))
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )


def test_websearch_capability_adds_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("swarm_sdk.core.swarm._websearch_tools", lambda: [_FakeSearchTool()])
    sdk = _sdk_with_flag(tmp_path, websearch=True)
    manifest = load_all_agent_manifests()["Researcher"]
    assert "web_search" in manifest.capabilities

    tools = sdk._node_tools(manifest, ["coder", "reviewer"])
    names = [getattr(tool, "name", "") for tool in tools]

    assert names[0] == "web_search_brief"
    assert "transfer_to_coder" in names and "transfer_to_reviewer" in names


def test_websearch_flag_off_leaves_handoffs_only(tmp_path: Path) -> None:
    sdk = _sdk_with_flag(tmp_path, websearch=False)
    manifest = load_all_agent_manifests()["Researcher"]

    tools = sdk._node_tools(manifest, ["coder", "reviewer"])
    names = [getattr(tool, "name", "") for tool in tools]

    assert "web_search_brief" not in names
    assert names == ["parse_syntax", "transfer_to_coder", "transfer_to_reviewer"]


def test_capability_without_flag_or_package_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("swarm_sdk.core.swarm._websearch_tools", lambda: [_FakeSearchTool()])
    sdk = _sdk_with_flag(tmp_path, websearch=True)
    coder = load_all_agent_manifests()["Coder"]
    assert "web_search" not in coder.capabilities

    tools = sdk._node_tools(coder, ["researcher", "reviewer"])
    names = [getattr(tool, "name", "") for tool in tools]

    assert "web_search_brief" not in names


def test_bundled_websearch_bridge_importable_when_installed() -> None:
    pytest.importorskip("WebSearch.agent_tools")
    from swarm_sdk.core.swarm import _websearch_tools

    names = [cast(Any, tool).name for tool in _websearch_tools()]
    assert "web_search_brief" in names and "web_search_hits" in names
