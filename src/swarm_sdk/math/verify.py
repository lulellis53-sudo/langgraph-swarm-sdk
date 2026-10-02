"""Computational verification of math claims by running a reproducible script.

The script runs in a separate ``python -I`` process with a scrubbed environment, a
temporary working directory and a wall-clock timeout, so a runaway or crashing script
cannot hang or take down the agent and cannot read its secrets. This is isolation of
failure and environment, **not** a security sandbox: the script is ordinary Python and
must still come from a trusted or reviewed source.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile

from swarm_sdk.math.types import VerificationResult

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_TOLERANCE = 1e-5
_MAX_OUTPUT_CHARS = 65536
_MARKER = "@@SWARM_VERIFY@@"

# Runs inside the child process: exec the script, compare ``res`` with ``expected``.
_RUNNER = r"""
import contextlib, io, json, math, sys
import numpy as np
import sympy as sp

MARKER = sys.argv[1]
req = json.loads(sys.stdin.read())
out = {"ok": False, "detail": ""}
try:
    ns = {"sp": sp, "np": np, "math": math}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(req["script"], "<verify>", "exec"), ns)
    if "res" not in ns:
        raise NameError("script must assign its answer to `res`")
    res, expected = ns["res"], req["expected"]
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        val = float(res)
        err = abs(val - expected)
        out.update(method="numeric", ok=bool(err <= req["tolerance"]), error_bound=err)
        if math.isnan(err):
            out.update(ok=False, error_bound=None, detail="result is NaN")
    else:
        text = str(res)
        if text == str(expected):
            same = True
        else:
            same = sp.simplify(sp.sympify(text) - sp.sympify(str(expected))) == 0
        out.update(method="sympy", ok=bool(same), error_bound=0.0 if same else None)
except BaseException as exc:
    out.update(method="error", detail=f"{type(exc).__name__}: {exc}")
sys.stdout.write(MARKER + json.dumps(out) + "\n")
"""


def verify_math_solution(
    claim: str,
    expected: float | int | str,
    script: str,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> VerificationResult:
    """Run ``script`` and check that its ``res`` matches ``expected``.

    The script sees ``sp`` (SymPy), ``np`` (NumPy) and ``math`` pre-imported and must
    assign its answer to ``res``. Numeric expectations compare within ``tolerance``;
    string expectations compare symbolically (``simplify(res - expected) == 0``).

    Args:
        claim: Human-readable claim being verified (kept for the caller's records).
        expected: The value the claim asserts.
        script: Python source that computes ``res``.
        tolerance: Absolute tolerance for numeric comparison.
        timeout_s: Wall-clock limit before the child process is killed.

    Returns:
        A result whose ``verified`` is False, with ``detail`` explaining why, on a
        mismatch, script error, missing ``res``, NaN or timeout; never raises for
        script failures.
    """
    del claim  # not needed to verify; callers keep it alongside the result
    request = json.dumps({"script": script, "expected": expected, "tolerance": tolerance})
    with tempfile.TemporaryDirectory(prefix="swarm-verify-") as workdir:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _RUNNER, _MARKER],
                input=request,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=workdir,
                env={"OMP_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _failed(script, f"timed out after {timeout_s:g}s")
    # Last marker line wins: the runner always writes its own verdict after the script ran.
    line = next(
        (
            ln
            for ln in reversed(proc.stdout[-_MAX_OUTPUT_CHARS:].splitlines())
            if ln.startswith(_MARKER)
        ),
        None,
    )
    if line is None:
        tail = proc.stderr.strip().splitlines()[-1:] or ["no result produced"]
        return _failed(script, f"verifier crashed (exit {proc.returncode}): {tail[0]}")
    data = json.loads(line[len(_MARKER) :])
    return VerificationResult(
        verified=bool(data["ok"]),
        method=str(data.get("method", "error")),
        script_snippet=script,
        error_bound=data.get("error_bound"),
        detail=str(data.get("detail", "")),
    )


def _failed(script: str, detail: str) -> VerificationResult:
    return VerificationResult(
        verified=False, method="error", script_snippet=script, error_bound=None, detail=detail
    )


__all__ = ["verify_math_solution"]
