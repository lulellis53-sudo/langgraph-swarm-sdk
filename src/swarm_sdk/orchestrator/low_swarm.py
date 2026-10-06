"""LangGraph state machine orchestrator for low-resource multi-agent swarm."""

from __future__ import annotations

import ast
import inspect
import logging
import resource
import sys
import time
from typing import Any, TypedDict, cast

from langgraph.graph import END, StateGraph

from swarm_sdk.core.jev_router import JevRouter, NoulDecision, ScoreDecision
from swarm_sdk.core.lifeguard_ast import MetaLifeguardAuditor
from swarm_sdk.core.rules import HostRuleEngine

logger = logging.getLogger(__name__)


class SwarmState(TypedDict, total=False):
    """Execution state schema tracked throughout the Swarm LangGraph."""

    task: str
    target_files: list[str]
    context_chunks: list[str]
    jev_decision: dict[str, Any]
    synthesized_code: dict[str, str]
    diff_patches: list[str]
    lifeguard_report: dict[str, Any]
    test_results: dict[str, Any]
    iteration: int
    metrics: dict[str, float]
    status: str
    error: str | None


class LowSwarmEngine:
    """LangGraph-powered state machine enforcing host constraints and Jev/Lifeguard invariants."""

    def __init__(
        self,
        rule_engine: HostRuleEngine | None = None,
        jev_router: JevRouter | None = None,
        rag_pipeline: Any = None,
        custom_synthesizer: Any = None,
        test_runner: Any = None,
    ) -> None:
        self.rule_engine: HostRuleEngine = rule_engine or HostRuleEngine()
        self.jev_router: JevRouter = jev_router or JevRouter()
        self.rag_pipeline: Any = rag_pipeline
        self.custom_synthesizer: Any = custom_synthesizer
        self.test_runner: Any = test_runner

        self.graph: StateGraph = self._build_graph()
        self.app = self.graph.compile()

    # ---------------------------------------------------------------------------
    # Memory Ceiling Guard
    # ---------------------------------------------------------------------------

    def get_current_rss_gb(self) -> float:
        """Returns the current process resident set size (RSS) in gigabytes."""
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            # macOS ru_maxrss is returned in bytes
            return usage / (1024**3)
        # Linux / Unix ru_maxrss is returned in kilobytes
        return usage / (1024**2)

    def check_memory_ceiling(self) -> float:
        """Enforces that process RSS does not exceed the host ceiling (< 13.6 GB)."""
        rss_gb = self.get_current_rss_gb()
        ceiling_gb = getattr(self.rule_engine.invariants, "ram_ceiling_gb", 13.6)
        if rss_gb >= ceiling_gb:
            raise MemoryError(
                f"Process RSS memory ({rss_gb:.2f} GB) exceeds host ceiling ({ceiling_gb:.2f} GB)"
            )
        return rss_gb

    # ---------------------------------------------------------------------------
    # Graph Construction
    # ---------------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(SwarmState)

        builder.add_node("jev_router_node", self.node_jev_router)
        builder.add_node("coder_node", self.node_coder)
        builder.add_node("lifeguard_node", self.node_lifeguard)
        builder.add_node("test_verifier_node", self.node_test_verifier)

        builder.set_entry_point("jev_router_node")

        builder.add_conditional_edges(
            "jev_router_node",
            self._route_after_router,
            {"coder_node": "coder_node", END: END},
        )
        builder.add_conditional_edges(
            "coder_node",
            self._route_after_coder,
            {"lifeguard_node": "lifeguard_node", END: END},
        )
        builder.add_conditional_edges(
            "lifeguard_node",
            self._route_after_lifeguard,
            {
                "test_verifier_node": "test_verifier_node",
                "coder_node": "coder_node",
                END: END,
            },
        )
        builder.add_edge("test_verifier_node", END)

        return builder

    # ---------------------------------------------------------------------------
    # StateGraph Nodes
    # ---------------------------------------------------------------------------

    def node_jev_router(self, state: SwarmState) -> dict[str, Any]:
        """Routes task, enforces Noul safety, scores complexity, and attaches RAG context."""
        try:
            rss = self.check_memory_ceiling()
        except MemoryError as exc:
            return {"status": "blocked", "error": str(exc)}

        task = state.get("task", "")
        context_chunks = list(state.get("context_chunks") or [])

        # Ingest RAG context if pipeline is configured and context is empty
        if self.rag_pipeline is not None and not context_chunks:
            try:
                if callable(self.rag_pipeline):
                    retrieved = self.rag_pipeline(task)
                elif hasattr(self.rag_pipeline, "query"):
                    retrieved = self.rag_pipeline.query(task)
                elif hasattr(self.rag_pipeline, "retrieve"):
                    retrieved = self.rag_pipeline.retrieve(task)
                else:
                    retrieved = None

                if isinstance(retrieved, list):
                    context_chunks = [
                        c.chunk.full_text
                        if hasattr(c, "chunk") and hasattr(c.chunk, "full_text")
                        else (c.full_text if hasattr(c, "full_text") else str(c))
                        for c in retrieved
                    ]
                elif isinstance(retrieved, str):
                    context_chunks = [retrieved]
            except Exception as exc:
                logger.warning("RAG pipeline retrieval failed: %s", exc)

        context_text = "\n".join(context_chunks)

        # 1. Noul Safety gate evaluation
        noul_decision: NoulDecision = self.jev_router.evaluate_noul(task, context=context_text)
        if not noul_decision.decision:
            return {
                "status": "blocked",
                "error": "Task blocked by safety gate",
                "jev_decision": {
                    "safe": False,
                    "noul": noul_decision.model_dump(),
                    "reasoning_tag": noul_decision.reasoning_tag,
                },
                "synthesized_code": {},
                "context_chunks": context_chunks,
                "metrics": {"rss_gb": rss},
            }

        # 2. Score complexity and model tiering
        score_decision: ScoreDecision = self.jev_router.evaluate_score(task, context=context_text)
        jev_decision = {
            "safe": True,
            "noul": noul_decision.model_dump(),
            "score": score_decision.score,
            "model_tier": score_decision.model_tier,
            "complexity_bucket": score_decision.complexity_bucket,
            "latency_ms": score_decision.latency_ms + noul_decision.latency_ms,
        }

        return {
            "jev_decision": jev_decision,
            "context_chunks": context_chunks,
            "status": "routed",
            "metrics": {"rss_gb": rss},
        }

    def node_coder(self, state: SwarmState) -> dict[str, Any]:
        """Synthesizes code for target_files using custom synthesizer or template generator."""
        try:
            rss = self.check_memory_ceiling()
        except MemoryError as exc:
            return {"status": "blocked", "error": str(exc)}

        if state.get("status") == "blocked":
            return {}

        task = state.get("task", "")
        target_files = state.get("target_files") or ["solution.py"]
        context_chunks = state.get("context_chunks") or []
        iteration = state.get("iteration", 0)

        synthesized_code: dict[str, str] = {}

        if self.custom_synthesizer is not None:
            try:
                sig = inspect.signature(self.custom_synthesizer)
                num_params = len(sig.parameters)
                if num_params == 1:
                    raw_res = self.custom_synthesizer(state)
                elif num_params == 2:
                    raw_res = self.custom_synthesizer(task, target_files)
                elif num_params == 3:
                    raw_res = self.custom_synthesizer(task, target_files, context_chunks)
                else:
                    raw_res = self.custom_synthesizer(task, target_files, context_chunks, iteration)
            except TypeError:
                raw_res = self.custom_synthesizer(state)

            if isinstance(raw_res, dict):
                synthesized_code = {str(k): str(v) for k, v in raw_res.items()}
            elif isinstance(raw_res, str):
                first_file = target_files[0] if target_files else "solution.py"
                synthesized_code = {first_file: raw_res}
        else:
            # Deterministic template generator
            for fname in target_files:
                extra_defs = ""
                task_lower = task.lower()
                if "memoryview" in task_lower or "zero-copy" in task_lower:
                    extra_defs = (
                        "\n\ndef extract_memoryview(buffer: bytes | bytearray) -> memoryview:\n"
                        '    """Extract zero-copy memoryview from buffer."""\n'
                        "    return memoryview(buffer)\n"
                    )
                context_comment = ""
                if context_chunks:
                    context_comment = f"\n# Grounded context chunks: {len(context_chunks)}\n"

                synthesized_code[fname] = (
                    f'"""Synthesized implementation for: {task}"""\n'
                    f"{context_comment}\n"
                    f"def run() -> str:\n"
                    f'    return "Success for {task}"\n'
                    f"{extra_defs}"
                )

        diff_patches = [
            f"--- /dev/null\n+++ b/{fname}\n@@ -0,0 +1 @@\n{code}"
            for fname, code in synthesized_code.items()
        ]

        return {
            "synthesized_code": synthesized_code,
            "diff_patches": diff_patches,
            "status": "synthesized",
            "metrics": {**state.get("metrics", {}), "rss_gb": rss},
        }

    def node_lifeguard(self, state: SwarmState) -> dict[str, Any]:
        """Audits synthesized code with MetaLifeguardAuditor for forbidden execution patterns."""
        try:
            rss = self.check_memory_ceiling()
        except MemoryError as exc:
            return {"status": "blocked", "error": str(exc)}

        if state.get("status") == "blocked":
            return {}

        synthesized_code = state.get("synthesized_code") or {}
        iteration = state.get("iteration", 0)

        all_approved = True
        all_violations: list[dict[str, Any]] = []
        total_inspected = 0
        has_prohibited = False
        has_unlazy = False

        for fname, code in synthesized_code.items():
            report = MetaLifeguardAuditor.audit_code(code)
            total_inspected += report.inspected_nodes
            if not report.is_approved:
                all_approved = False
            for v in report.violations:
                v_dict = v.model_dump()
                v_dict["file"] = fname
                all_violations.append(v_dict)
            if report.has_prohibited_calls:
                has_prohibited = True
            if report.has_unlazy_imports:
                has_unlazy = True

        report_dict: dict[str, Any] = {
            "is_approved": all_approved,
            "violations": all_violations,
            "inspected_nodes": total_inspected,
            "has_prohibited_calls": has_prohibited,
            "has_unlazy_imports": has_unlazy,
        }

        if all_approved:
            return {
                "lifeguard_report": report_dict,
                "status": "approved",
                "metrics": {**state.get("metrics", {}), "rss_gb": rss},
            }

        # Handle rejection & resynthesis routing feedback
        next_iter = iteration + 1
        feedback_lines = [
            f"{v.get('file')}:{v.get('line')}:{v.get('col')} "
            f"[{v.get('category')}]: {v.get('message')}"
            for v in all_violations
        ]
        feedback = "Lifeguard audit violations:\n" + "\n".join(feedback_lines)
        context_chunks = list(state.get("context_chunks") or [])
        context_chunks.append(feedback)

        if next_iter >= 3:
            return {
                "lifeguard_report": report_dict,
                "iteration": next_iter,
                "status": "blocked",
                "error": "Max resynthesis iterations reached",
                "context_chunks": context_chunks,
                "metrics": {**state.get("metrics", {}), "rss_gb": rss},
            }

        return {
            "lifeguard_report": report_dict,
            "iteration": next_iter,
            "status": "resynthesizing",
            "context_chunks": context_chunks,
            "metrics": {**state.get("metrics", {}), "rss_gb": rss},
        }

    def node_test_verifier(self, state: SwarmState) -> dict[str, Any]:
        """Validates Python syntax with ast.parse and runs optional test runner."""
        try:
            rss = self.check_memory_ceiling()
        except MemoryError as exc:
            return {"status": "blocked", "error": str(exc)}

        if state.get("status") == "blocked":
            return {}

        synthesized_code = state.get("synthesized_code") or {}

        # 1. AST syntax parsing
        for fname, code in synthesized_code.items():
            try:
                ast.parse(code)
            except SyntaxError as e:
                return {
                    "test_results": {
                        "syntax_valid": False,
                        "passed": False,
                        "error": f"Syntax error in {fname}: {e.msg} at line {e.lineno}",
                    },
                    "status": "failed",
                    "error": f"Syntax error in {fname}: {e}",
                    "metrics": {**state.get("metrics", {}), "rss_gb": rss},
                }

        # 2. Optional test runner execution
        test_results: dict[str, Any] = {"syntax_valid": True, "passed": True}
        if self.test_runner is not None:
            try:
                sig = inspect.signature(self.test_runner)
                if len(sig.parameters) == 1:
                    tr_output = self.test_runner(state)
                else:
                    tr_output = self.test_runner(synthesized_code)

                if isinstance(tr_output, dict):
                    passed = bool(
                        tr_output.get("passed", True) and not tr_output.get("failed", False)
                    )
                    test_results.update(tr_output)
                    test_results["passed"] = passed
                elif isinstance(tr_output, bool):
                    test_results["passed"] = tr_output
                else:
                    test_results["passed"] = True
                    test_results["output"] = str(tr_output)

                if not test_results["passed"]:
                    return {
                        "test_results": test_results,
                        "status": "failed",
                        "error": test_results.get("error", "Test runner validation failed"),
                        "metrics": {**state.get("metrics", {}), "rss_gb": rss},
                    }
            except Exception as exc:
                return {
                    "test_results": {"syntax_valid": True, "passed": False, "error": str(exc)},
                    "status": "failed",
                    "error": f"Test runner execution error: {exc}",
                    "metrics": {**state.get("metrics", {}), "rss_gb": rss},
                }

        return {
            "test_results": test_results,
            "status": "success",
            "error": None,
            "metrics": {**state.get("metrics", {}), "rss_gb": rss},
        }

    # Method aliases for node compatibility
    jev_router_node = node_jev_router
    coder_node = node_coder
    lifeguard_node = node_lifeguard
    test_verifier_node = node_test_verifier

    # ---------------------------------------------------------------------------
    # Conditional Routing Functions
    # ---------------------------------------------------------------------------

    def _route_after_router(self, state: SwarmState) -> str:
        if state.get("status") == "blocked":
            return END
        return "coder_node"

    def _route_after_coder(self, state: SwarmState) -> str:
        if state.get("status") == "blocked":
            return END
        return "lifeguard_node"

    def _route_after_lifeguard(self, state: SwarmState) -> str:
        if state.get("status") == "blocked":
            return END
        report = state.get("lifeguard_report") or {}
        if report.get("is_approved", False):
            return "test_verifier_node"
        if state.get("iteration", 0) >= 3:
            return END
        return "coder_node"

    # ---------------------------------------------------------------------------
    # Public Execution Entrypoint
    # ---------------------------------------------------------------------------

    def run(
        self,
        task: str,
        target_files: list[str] | None = None,
        initial_context: list[str] | None = None,
        profile: bool = False,
    ) -> SwarmState:
        """Executes the state graph and returns the completed SwarmState."""
        files = list(target_files) if target_files else ["solution.py"]
        context = list(initial_context) if initial_context else []
        initial_state: SwarmState = {
            "task": task,
            "target_files": files,
            "context_chunks": context,
            "iteration": 0,
            "status": "initialized",
            "synthesized_code": {},
            "diff_patches": [],
            "metrics": {},
        }

        start_time = time.perf_counter()
        start_cpu = time.process_time()
        try:
            final_state = self.app.invoke(initial_state)
            state_res = cast(SwarmState, final_state)
            if profile:
                if "metrics" not in state_res or not isinstance(state_res["metrics"], dict):
                    state_res["metrics"] = {}
                state_res["metrics"]["wall_clock_ms"] = (time.perf_counter() - start_time) * 1000.0
                state_res["metrics"]["cpu_time_ms"] = (time.process_time() - start_cpu) * 1000.0
                state_res["metrics"]["rss_gb"] = state_res["metrics"].get(
                    "rss_gb", self.get_current_rss_gb()
                )
            return state_res
        except MemoryError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            cpu_ms = (time.process_time() - start_cpu) * 1000.0
            err_metrics = {"rss_gb": self.get_current_rss_gb()}
            if profile:
                err_metrics["wall_clock_ms"] = elapsed_ms
                err_metrics["cpu_time_ms"] = cpu_ms
            return SwarmState(
                task=task,
                target_files=files,
                context_chunks=context,
                status="blocked",
                error=str(exc),
                iteration=0,
                synthesized_code={},
                diff_patches=[],
                metrics=err_metrics,
            )


__all__ = [
    "LowSwarmEngine",
    "SwarmState",
]
