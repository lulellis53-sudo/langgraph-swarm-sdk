import operator
from pathlib import Path
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.checkpoint import open_checkpointer
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


class _State(TypedDict):
    log: Annotated[list[str], operator.add]


def _app(saver):
    graph = StateGraph(_State)
    graph.add_node("step", lambda state: {"log": ["x"]})
    graph.add_edge(START, "step")
    graph.add_edge("step", END)
    return graph.compile(checkpointer=saver)


def _sdk(tmp_path: Path, checkpoint: Path, *, max_threads: int = 200) -> SwarmSDK:
    model = ScriptedModel(script=Script([answer("ok")]))
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        checkpoint_path=str(checkpoint),
        embed_dim=32,
        memory_backend="opencl",
    )
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        max_threads=max_threads,
    )


def test_none_path_is_in_memory() -> None:
    assert type(open_checkpointer(None)).__name__ == "InMemorySaver"


def test_sqlite_checkpoint_survives_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "cp.db")
    config = {"configurable": {"thread_id": "t1"}}
    _app(open_checkpointer(path)).invoke({"log": []}, config)
    state = _app(open_checkpointer(path)).get_state(config)
    assert state.values["log"] == ["x"]


def test_missing_parent_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "cp.db"
    open_checkpointer(str(path))
    assert path.exists()


def test_restart_keeps_existing_thread(tmp_path: Path) -> None:
    checkpoint = tmp_path / "cp.db"
    config = {"configurable": {"thread_id": "t"}}
    first = _sdk(tmp_path, checkpoint)
    assert first._is_new_thread("t") is True
    _app(first._checkpointer).invoke({"log": []}, config)
    second = _sdk(tmp_path, checkpoint)
    assert second._is_new_thread("t") is False
    assert second._is_new_thread("other") is True


def test_eviction_does_not_delete_durable_checkpoints(tmp_path: Path) -> None:
    checkpoint = tmp_path / "cp.db"
    sdk = _sdk(tmp_path, checkpoint, max_threads=2)
    _app(sdk._checkpointer).invoke({"log": []}, {"configurable": {"thread_id": "keep"}})
    for name in ("keep", "b", "c"):  # third id pushes past the cap and evicts "keep"
        sdk._register_thread(name)
    assert sdk._is_new_thread("keep") is False
