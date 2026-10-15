"""Tests for LowSwarmEngine LangGraph state machine and memory ceiling guard."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from swarm_sdk.orchestrator import LowSwarmEngine, SwarmState


class TestLowSwarmEngine:
    """Test suite for LowSwarmEngine end-to-end orchestration."""

    def test_happy_path_success(self) -> None:
        """Happy path: task -> router -> coder -> lifeguard passes -> test verifier passes -> status='success'."""
        engine = LowSwarmEngine()
        result = engine.run(
            task="Create a calculator module with add and subtract functions",
            target_files=["calculator.py"],
        )

        assert result["status"] == "success"
        assert result.get("error") is None
        assert "calculator.py" in result["synthesized_code"]
        assert "def " in result["synthesized_code"]["calculator.py"]
        assert result["lifeguard_report"]["is_approved"] is True
        assert result["test_results"]["syntax_valid"] is True
        assert result["test_results"]["passed"] is True
        assert result["jev_decision"]["safe"] is True
        assert result["iteration"] == 0

    def test_safety_block_destructive_command(self) -> None:
        """Safety block: task with dangerous command (e.g. rm -rf /) -> blocked at router."""
        engine = LowSwarmEngine()
        result = engine.run(
            task="rm -rf / --no-preserve-root && echo erased",
            target_files=["dangerous.py"],
        )

        assert result["status"] == "blocked"
        assert result["error"] == "Task blocked by safety gate"
        assert result["jev_decision"]["safe"] is False
        assert result.get("synthesized_code") == {}

    def test_lifeguard_resynthesis_loop_fixes_code(self) -> None:
        """Lifeguard resynthesis loop: coder initially outputs top-level os.system -> lifeguard rejects -> loops back -> coder fixes -> passes."""

        def iterative_synthesizer(state: SwarmState) -> dict[str, str]:
            iteration = state.get("iteration", 0)
            if iteration == 0:
                # Top-level prohibited call os.system
                return {
                    "worker.py": (
                        "import os\nos.system('echo unsafe')\ndef do_work():\n    return 42\n"
                    )
                }
            else:
                # Clean, compliant code
                return {"worker.py": ("def do_work():\n    return 42\n")}

        engine = LowSwarmEngine(custom_synthesizer=iterative_synthesizer)
        result = engine.run(
            task="Implement safe worker function",
            target_files=["worker.py"],
        )

        assert result["status"] == "success"
        assert result["iteration"] == 1
        assert result["lifeguard_report"]["is_approved"] is True
        assert "os.system" not in result["synthesized_code"]["worker.py"]
        assert "def do_work():" in result["synthesized_code"]["worker.py"]

    def test_circuit_breaker_halts_at_max_iterations(self) -> None:
        """Circuit breaker: coder continuously outputs bad code -> halts at iteration 3."""

        def bad_synthesizer(state: SwarmState) -> dict[str, str]:
            return {"exploit.py": ("import os\nos.system('cat /etc/shadow')\n")}

        engine = LowSwarmEngine(custom_synthesizer=bad_synthesizer)
        result = engine.run(
            task="Generate system monitor script",
            target_files=["exploit.py"],
        )

        assert result["status"] == "blocked"
        assert result["iteration"] == 3
        assert result["error"] == "Max resynthesis iterations reached"
        assert result["lifeguard_report"]["is_approved"] is False
        assert len(result["lifeguard_report"]["violations"]) > 0

    def test_memory_ceiling_guard_triggers_block(self) -> None:
        """Memory ceiling guard: RSS exceeding 13.6 GB ceiling halts execution and blocks state."""
        engine = LowSwarmEngine()

        with patch.object(engine, "get_current_rss_gb", return_value=14.2):
            with pytest.raises(MemoryError) as exc_info:
                engine.check_memory_ceiling()
            assert "exceeds host ceiling" in str(exc_info.value)

            result = engine.run(
                task="Synthesize large module",
                target_files=["large.py"],
            )
            assert result["status"] == "blocked"
            assert "exceeds host ceiling" in str(result["error"])

    def test_syntax_error_caught_by_test_verifier(self) -> None:
        """Syntax error in synthesized code fails in test_verifier node."""
        state: SwarmState = {
            "task": "syntax test",
            "target_files": ["broken.py"],
            "synthesized_code": {"broken.py": "def invalid_syntax(:\n    pass"},
        }
        engine = LowSwarmEngine()
        update = engine.node_test_verifier(state)

        assert update["status"] == "failed"
        assert "Syntax error" in str(update["error"])
        assert update["test_results"]["syntax_valid"] is False

    def test_custom_test_runner_pass_and_fail(self) -> None:
        """Custom test_runner validates synthesized code execution."""
        # Failing runner
        failing_runner = lambda state: {
            "passed": False,
            "error": "Unit tests failed: 2 assertion errors",
        }
        engine_fail = LowSwarmEngine(test_runner=failing_runner)
        res_fail = engine_fail.run("Test task", target_files=["module.py"])
        assert res_fail["status"] == "failed"
        assert "Unit tests failed" in str(res_fail["error"])

        # Passing runner
        passing_runner = lambda state: {"passed": True, "tests_run": 5}
        engine_pass = LowSwarmEngine(test_runner=passing_runner)
        res_pass = engine_pass.run("Test task", target_files=["module.py"])
        assert res_pass["status"] == "success"
        assert res_pass["test_results"]["tests_run"] == 5

    def test_rag_pipeline_context_injection(self) -> None:
        """RAG pipeline injects context chunks during router execution."""
        mock_rag = lambda task: ["Chunk A: architectural guideline", "Chunk B: invariant rule"]
        engine = LowSwarmEngine(rag_pipeline=mock_rag)
        result = engine.run("Implement optimized vector loop", target_files=["vector.py"])

        assert result["status"] == "success"
        assert "Chunk A: architectural guideline" in result["context_chunks"]
        assert "Chunk B: invariant rule" in result["context_chunks"]

    def test_orchestrator_init_exports(self) -> None:
        """Verify LowSwarmEngine and SwarmState are properly re-exported in orchestrator __init__."""
        import swarm_sdk.orchestrator as orch

        assert hasattr(orch, "LowSwarmEngine")
        assert hasattr(orch, "SwarmState")
        assert "LowSwarmEngine" in orch.__all__
        assert "SwarmState" in orch.__all__

    def test_router_model_tiers(self) -> None:
        """Verify complex tasks map to 'pro' tier and trivial tasks map to 'flash_lite'."""
        engine = LowSwarmEngine()

        # Pro tier: multi-file architecture concurrency
        pro_res = engine.run(
            "Implement multi-file architecture with concurrent thread pool and mutex"
        )
        assert pro_res["jev_decision"]["model_tier"] == "pro"
        assert pro_res["jev_decision"]["complexity_bucket"] == "high"

        # Flash-lite tier: typo / docstring fix
        lite_res = engine.run("Fix typo in docstrings")
        assert lite_res["jev_decision"]["model_tier"] == "flash_lite"
        assert lite_res["jev_decision"]["complexity_bucket"] == "low"

    def test_custom_synthesizer_single_string_return(self) -> None:
        """Custom synthesizer returning a single code string is mapped to first target file."""
        engine = LowSwarmEngine(
            custom_synthesizer=lambda task, files: "def greet(): return 'hello'"
        )
        res = engine.run("Greet user", target_files=["greeter.py"])
        assert res["status"] == "success"
        assert "greeter.py" in res["synthesized_code"]
        assert res["synthesized_code"]["greeter.py"] == "def greet(): return 'hello'"

    def test_custom_test_runner_exception_handling(self) -> None:
        """Custom test_runner raising an unexpected exception sets status to failed."""

        def exploding_runner(state):
            raise RuntimeError("Unexpected runner crash")

        engine = LowSwarmEngine(test_runner=exploding_runner)
        res = engine.run("Run tests", target_files=["mod.py"])
        assert res["status"] == "failed"
        assert "Unexpected runner crash" in str(res["error"])
        assert res["test_results"]["passed"] is False
