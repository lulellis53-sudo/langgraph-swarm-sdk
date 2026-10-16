"""Isolated A/B benchmark: HEAD ("before") vs working tree ("after").

Each measurement runs in its **own subprocess**, so import-time state, warm
caches and allocator behaviour cannot leak between the two arms. That matters
here because three of the optimizations are import-time or connection-time
effects, which an in-process bench would silently flatten.

Usage (from the BotDeal worktree, which has the dashboard deps):

    PYTHONPATH="$HOME/BotDeal" ./.venv/bin/python Agents/benchmark/ab_optimizations.py

The "before" arm is materialised by `git show HEAD:<path>` into a temp tree, so
nothing in the repository is modified. Results are printed as a table plus a
machine-readable JSON blob for later comparison.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Files whose HEAD revision differs from the working tree, i.e. the arms.
TRACKED = (
    "src/swarm_sdk/__init__.py",
    "src/swarm_sdk/retrieval/cache.py",
    "src/swarm_sdk/cli.py",
)


def _materialise_arms(root: Path) -> tuple[Path, Path]:
    """Return (before_root, after_root) each containing an importable tree.

    Each arm gets ``<arm>/src/swarm_sdk`` so that putting ``<arm>/src`` on
    ``PYTHONPATH`` shadows the installed package. Only the touched files differ
    between the arms; everything else is the live working tree.
    """
    before = root / "before"
    after = root / "after"
    sdk_src = REPO / "src" / "swarm_sdk"
    for arm in (before, after):
        shutil.copytree(sdk_src, arm / "src" / "swarm_sdk", dirs_exist_ok=True)
        _rstrip_pycache(arm)
    for rel in TRACKED:
        # rel is like "src/swarm_sdk/__init__.py"; both arms keep the src/ level.
        target = Path(rel)
        head = subprocess.run(
            ["git", "-C", str(REPO), "show", f"HEAD:{rel}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        (before / target).write_text(head)
    return before, after


def _rstrip_pycache(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


# --- the probe script each arm runs -------------------------------------------
# Written to a temp file rather than passed with -c to keep quoting simple.

PROBE = textwrap.dedent(
    '''
    """One arm's measurements. Runs in a fresh interpreter."""
    import json, os, statistics, sys, tempfile, time

    def timed(fn, repeat=7, warmup=2):
        for _ in range(warmup):
            fn()
        samples = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - t0)
        return statistics.median(samples)

    out = {"arm": os.environ["AB_ARM"]}

    # 1. import cost of the SDK facade
    def import_facade():
        for mod in [m for m in sys.modules if m.startswith("swarm_sdk")]:
            del sys.modules[mod]
        import swarm_sdk  # noqa: F401
    out["import_facade_ms"] = timed(import_facade, repeat=5, warmup=1) * 1000

    # 2. modules pulled in by that import (eager-load evidence)
    for mod in [m for m in sys.modules if m.startswith("swarm_sdk")]:
        del sys.modules[mod]
    import swarm_sdk  # noqa: F401
    out["sdk_modules_loaded"] = len([m for m in sys.modules if m.startswith("swarm_sdk")])
    out["numpy_eager"] = "numpy" in sys.modules

    # 3. semantic-cache lookup on a populated store
    import numpy as np
    from swarm_sdk.retrieval.cache import SemanticCache

    class FakeEmbedder:
        dim = 384
        def embed(self, texts):
            rng = np.random.default_rng(abs(hash(texts[0])) % (2**32))
            return [rng.random(384).astype(np.float32) for _ in texts]

    path = tempfile.mktemp(suffix=".db")
    cache = SemanticCache(embedder=FakeEmbedder(), path=path, threshold=0.99)
    rows = 5000
    for i in range(rows):
        cache.store(f"q{i}", f"a{i}")
    out["cache_rows"] = rows
    out["journal_mode"] = cache._conn.execute("PRAGMA journal_mode").fetchone()[0]
    out["synchronous"] = cache._conn.execute("PRAGMA synchronous").fetchone()[0]

    misses = [f"miss-{i}-{time.time()}" for i in range(60)]
    cache.lookup(misses[0])          # warm the scan matrix
    t0 = time.perf_counter()
    for m in misses:
        cache.lookup(m)
    out["cache_lookup_ms"] = (time.perf_counter() - t0) / len(misses) * 1000

    # 4. per-row vs batched writes. `timed` returns SECONDS, and the ratio
    #    between the two arms is what matters; the probe converts once at the
    #    end so the reported unit is milliseconds.
    def per_row():
        _db = tempfile.mktemp(suffix=".db")
        c = SemanticCache(embedder=FakeEmbedder(), path=_db, threshold=0.9)
        t = time.perf_counter()
        for i in range(600):
            c.store(f"r{i}", f"b{i}")
        dt = time.perf_counter() - t
        c._conn.close()
        return dt
    out["store_per_row_ms"] = timed(per_row, repeat=3, warmup=1) * 1000

    if hasattr(cache, "store_many"):
        def batched():
            _db = tempfile.mktemp(suffix=".db")
            c = SemanticCache(embedder=FakeEmbedder(), path=_db, threshold=0.9)
            t = time.perf_counter()
            c.store_many([(f"r{i}", f"b{i}") for i in range(600)])
            dt = time.perf_counter() - t
            c._conn.close()
            return dt
        out["store_batched_ms"] = timed(batched, repeat=3, warmup=1) * 1000
    else:
        out["store_batched_ms"] = None

    out["has_close"] = hasattr(cache, "close")
    out["has_store_many"] = hasattr(cache, "store_many")

    # 5. peak RSS of the arm (macOS reports ru_maxrss in bytes, Linux in KiB).
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out["peak_rss_mb"] = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024

    # 6. scoring cost in isolation: pure matmul vs the norm-recomputing path.
    import numpy as _np
    from swarm_sdk.gpu import batch_cosine as _bc
    big = _np.random.default_rng(0).random((10000, 384), dtype=_np.float32)
    qv = _np.random.default_rng(1).random(384, dtype=_np.float32)
    out["cosine_unnorm_ms"] = timed(lambda: _bc(qv, big), repeat=5, warmup=1) * 1000
    norms = _np.linalg.norm(big, axis=1, keepdims=True)
    normed = _np.ascontiguousarray(big / _np.where(norms > 0, norms, 1.0), dtype=_np.float32)
    out["matmul_pre_normed_ms"] = timed(lambda: normed @ qv, repeat=5, warmup=1) * 1000
    out["scores_agree"] = bool(_np.allclose(_bc(qv, big), _bc(qv, normed), atol=1e-5))
    try:
        cache.close()
    except Exception:
        pass
    print(json.dumps(out))
    '''
)


def _collect_interleaved(
    before_root: Path, after_root: Path, rounds: int
) -> tuple[dict[str, object], dict[str, object]]:
    """Run before/after alternately, then take each metric's median.

    Interleaving matters on a shared machine: measuring all of ``before`` and
    then all of ``after`` lets CPU frequency scaling, thermal drift or another
    process bias one entire arm. Alternating spreads any drift across both.
    """
    runs: dict[str, list[dict[str, object]]] = {"before": [], "after": []}
    for _ in range(rounds):
        runs["before"].append(_run_arm_once(before_root, "before"))
        runs["after"].append(_run_arm_once(after_root, "after"))

    def merge(arm: str) -> dict[str, object]:
        samples = runs[arm]
        merged: dict[str, object] = {"arm": arm}
        keys = [k for k in samples[0] if k != "arm"]
        numeric = [
            k
            for k in keys
            if all(
                isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool)
                for s in samples
            )
        ]
        for key in numeric:
            merged[key] = statistics.median([s[key] for s in samples])  # type: ignore[type-var]
            merged.setdefault("_spread", {})  # type: ignore[union-attr]
            merged["_spread"][key] = max(s[key] for s in samples) - min(  # type: ignore[index,type-var]
                s[key] for s in samples
            )
        for key in keys:
            if key not in merged:
                merged[key] = samples[0][key]
        return merged

    return merge("before"), merge("after")


def _run_arm(arm_root: Path, label: str, repeats: int = 3) -> dict[str, object]:
    """Run the probe ``repeats`` times in fresh interpreters; keep the median.

    Subprocess isolation removes cross-arm contamination, but a single pass is
    still noisy on a shared machine, so each metric is the median of
    ``repeats`` independent processes.
    """
    runs: list[dict[str, object]] = []
    for _ in range(repeats):
        runs.append(_run_arm_once(arm_root, label))
    merged: dict[str, object] = {"arm": label}
    numeric = [
        key
        for key in runs[0]
        if key != "arm"
        and all(
            isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool) for r in runs
        )
    ]
    for key in numeric:
        merged[key] = statistics.median([r[key] for r in runs])  # type: ignore[type-var]
    for key in runs[0]:
        if key not in merged:
            merged[key] = runs[0][key]
    if repeats > 1:
        spread = {
            key: max(r[key] for r in runs) - min(r[key] for r in runs)  # type: ignore[type-var]
            for key in numeric
        }
        merged["_spread"] = spread
    return merged


def _run_arm_once(arm_root: Path, label: str) -> dict[str, object]:
    """Run the probe in a fresh interpreter against one arm."""
    probe = arm_root / "_probe.py"
    probe.write_text(PROBE)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(arm_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["AB_ARM"] = label
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
    )
    if proc.returncode != 0:
        return {"arm": label, "error": proc.stderr.strip()[-800:]}
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")][-1]
    return json.loads(line)  # type: ignore[no-any-return]


def main(argv: list[str] | None = None) -> int:
    """Run both arms and print a comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit raw JSON only")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="interleaved before/after rounds; each metric is the median (default 3)",
    )
    args = parser.parse_args(argv)

    # Guard: the probe is embedded source, so a bad edit inside the string is
    # invisible to ruff and only shows up as a subprocess failure. Fail loudly here.
    try:
        ast.parse(PROBE)
    except SyntaxError as exc:
        print(f"PROBE is not valid Python (line {exc.lineno}): {exc.msg}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="ab-opt-") as tmp:
        root = Path(tmp)
        before_root, after_root = _materialise_arms(root)
        before, after = _collect_interleaved(before_root, after_root, rounds=args.repeats)

    if args.json:
        print(json.dumps({"before": before, "after": after}, indent=2))
        return 0

    if "error" in before or "error" in after:
        print("one arm failed:")
        for arm in (before, after):
            if "error" in arm:
                print(f"  {arm['arm']}: {arm['error']}")
        return 1

    def show(key: str, unit: str = "", lower_is_better: bool = True) -> None:
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            print(f"{key:26} {'n/a (only one arm has it)':>26}")
            return
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) and b:
            ratio = (b / a) if lower_is_better else (a / b)
            verdict = "faster" if ratio > 1.05 else ("slower" if ratio < 0.95 else "SAME (noise)")
            # Spread from the repeated runs, so a thin margin is visible as noise.
            sb = (before.get("_spread") or {}).get(key)
            sa = (after.get("_spread") or {}).get(key)
            note = ""
            if isinstance(sb, (int, float)) and isinstance(sa, (int, float)):
                worst = max(sb, sa)
                if worst > abs(a - b):
                    note = f"  (±{worst:.2f} > delta {abs(a - b):.2f} - within noise)"
            print(f"{key:26} {b:>12.2f}{unit} {a:>12.2f}{unit} {ratio:>7.2f}x {verdict}{note}")
        else:
            print(f"{key:26} {str(b):>13} {str(a):>13}")

    print()
    print(f"{'metric':26} {'before':>14} {'after':>14} {'ratio':>8}")
    print("-" * 68)
    show("import_facade_ms", " ms")
    show("sdk_modules_loaded", " mods")
    show("cache_lookup_ms", " ms")
    show("store_per_row_ms", " ms")
    show("peak_rss_mb", " MB")
    print("-" * 68)
    print("scoring in isolation (arm-independent, sanity check):")
    for key in ("cosine_unnorm_ms", "matmul_pre_normed_ms"):
        v = after.get(key) or before.get(key)
        print(f"  {key:24} {v:>10.2f} ms" if isinstance(v, (int, float)) else f"  {key}: n/a")
    agree = after.get("scores_agree")
    if agree is None:
        agree = before.get("scores_agree")
    print(f"  {'scores_agree':24} {str(agree):>10}")
    if args.json:
        pass
    elif before.get("store_batched_ms") or after.get("store_batched_ms"):
        b = after.get("store_batched_ms")
        p = after.get("store_per_row_ms")
        if b and p:
            print(f"  per-row vs batched (after) {p:.1f} ms vs {b:.1f} ms -> {p / b:.1f}x")
    print("-" * 68)
    for key in ("numpy_eager", "journal_mode", "synchronous", "has_close", "has_store_many"):
        print(f"{key:26} {str(before.get(key)):>14} {str(after.get(key)):>14}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
