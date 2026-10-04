"""Token-saving context middleware on swarm agent nodes (§ orchestration)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from langchain.agents.middleware import ContextEditingMiddleware, SummarizationMiddleware

from benchmark.tests.fakes import Script, ScriptedModel, answer, handoff
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.models.chat import message_text
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


class RecordingModel(ScriptedModel):
    """ScriptedModel that also records the full per-call transcript."""

    transcripts: list[str] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.transcripts.append("\n".join(message_text(m) for m in messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


def _sdk(tmp_path: Path, **overrides: Any) -> SwarmSDK:
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        embed_dim=32,
        max_tokens=4096,
        memory_backend="opencl",
        **overrides,
    )
    model = ScriptedModel(script=Script([answer('{"mode":"swarm","tasks":[]}')]))
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=ScriptedModel(
            script=Script(
                [handoff("coder"), handoff("researcher"), handoff("coder"), answer("done")]
            )
        ),
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )


def test_middleware_empty_when_both_flags_off(tmp_path: Path) -> None:
    sdk = _sdk(tmp_path, swarm_context_editing=False, swarm_summarization=False)
    assert sdk._node_middleware() == []


def test_context_editing_on_by_default(tmp_path: Path) -> None:
    sdk = _sdk(tmp_path)
    middleware = sdk._node_middleware()
    assert len(middleware) == 1
    assert isinstance(middleware[0], ContextEditingMiddleware)


def test_summarization_is_opt_in(tmp_path: Path) -> None:
    sdk = _sdk(tmp_path, swarm_summarization=True)
    middleware = sdk._node_middleware()
    assert len(middleware) == 2
    assert isinstance(middleware[1], SummarizationMiddleware)


async def test_stale_handoff_results_are_cleared(tmp_path: Path) -> None:
    """Past the trigger, only the most recent tool use stays verbatim."""
    sdk = _sdk(
        tmp_path,
        swarm_edit_trigger_tokens=64,
        swarm_edit_keep_tool_uses=1,
    )
    # ScriptedModel records only the last message; record the full transcript.
    recorder = RecordingModel(script=cast(Any, sdk._specialist_model).script)
    sdk._specialist_model = recorder
    sdk._compiled = None  # rebuild the graph with the recording specialist

    filler = "filler " * 200  # pushes the transcript past the 64-token trigger
    result = await sdk.run(filler, "thread")

    assert result.mode == "swarm"
    assert result.text == "done"
    # Four specialist model calls: three handoffs, then the final answer. On the
    # final call the transcript holds three tool uses but keep=1, so the two
    # older handoff results are replaced by the placeholder.
    final_prompt = recorder.transcripts[3]
    assert "[cleared]" in final_prompt
    assert "Successfully transferred to researcher" not in final_prompt
    assert "Successfully transferred to coder" in final_prompt  # most recent, kept


async def test_small_conversations_are_untouched(tmp_path: Path) -> None:
    """Below the trigger nothing is edited (default trigger, small ping-pong)."""
    sdk = _sdk(tmp_path)
    specialist_script = cast(Any, sdk._specialist_model).script

    await sdk.run("please code this", "thread")

    first_specialist_call = specialist_script.seen[0]
    assert "[cleared]" not in first_specialist_call
