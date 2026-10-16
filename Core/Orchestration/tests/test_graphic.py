"""Graph graphic: Mermaid text and files, offline (no mermaid.ink call)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestration.graph import build_graph
from orchestration.graphic import render_mermaid, write_graph_files


@pytest.fixture
def compiled():
    return build_graph(FakeListChatModel(responses=["p", "a"]), lambda plan: "n")


def test_render_mermaid_lists_every_node(compiled) -> None:
    text = render_mermaid(compiled)
    for node in ("planner", "researcher", "writer"):
        assert node in text


def test_write_graph_files_creates_mmd_and_md(compiled, tmp_path: Path) -> None:
    paths = write_graph_files(compiled, tmp_path / "out", name="orch")
    assert [p.name for p in paths] == ["orch.mmd", "orch.md"]
    assert "planner" in paths[0].read_text(encoding="utf-8")
    assert paths[1].read_text(encoding="utf-8").startswith("```mermaid\n")


def test_write_graph_files_rejects_path_in_name(compiled, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name"):
        write_graph_files(compiled, tmp_path, name="../evil")
