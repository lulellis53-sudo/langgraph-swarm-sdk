# Toolchain findings

Verified findings about compilers, CPython versions, and dependency build
toolchains for this repository. Facts are measured, not assumed; each topic
dates its verification. Related: [AGENTS.md](AGENTS.md) (repo map, quality
gate), [Agents/benchmark/README.md](Agents/benchmark/README.md) (measured
improvements).

---

## Topic: C compiler toolchains

Verified 2026-10-01 on the Intel MacBook Pro (macOS x86_64).

- The machine's default toolchain is a custom **LLVM 23.1.1 clang**
  (`~/.local/opt/llvm-23.1.1/bin/clang`) with aggressive flags
  (`-O3 -march=native -fuse-ld=lld`). It **cannot build Python C extensions**:
  it has no macOS SDK sysroot, so every compile dies with
  `fatal error: 'assert.h' file not found` from `Python.h`.
- Fix: build with the system toolchain and cleared flags:

  ```bash
  CC=/usr/bin/clang CXX=/usr/bin/clang++ CFLAGS= LDFLAGS=
  ```

- `uv` caches built wheels per interpreter version, so a toolchain override is
  only paid once per package/version pair.
- The same limitation is already encoded in `pyproject.toml`:
  `no-build-package = ["cryptography"]` and the `fastembed`/`onnxruntime`
  platform markers (`sys_platform != 'darwin' or platform_machine != 'x86_64'`).

---

## Topic: Arch Linux on the MacBook 2019 (x86_64, AMD Radeon Pro 5300M)

Wheel coverage verified 2026-10-01 against PyPI metadata for Linux x86_64;
toolchain facts are Arch-standard (no Arch host was run in this session).
Most macOS topics above do not apply:

- **Toolchain**: Arch ships current gcc/clang with kernel and glibc headers,
  so the "assert.h not found" failure does not exist. Every C/Cython/Meson
  sdist in the dependency map builds out of the box with `base-devel` +
  `ninja`. The custom `-march=native`/`lld` flags are optional, not required.
- **glibc**: rolling release (≥ 2.42), so every `manylinux_2_28` wheel applies.
- **onnxruntime**: 6 manylinux x86_64 wheels for 1.30.0 → the `embed`/`ml`
  extras work unmarked on Linux (the pyproject markers exclude only
  darwin-x86_64).
- **faiss-cpu**: one manylinux wheel tagged `cp39-abi3` → installs on 3.15.
  **faiss-gpu** stays unusable on this hardware (CUDA wheels, AMD GPU): the
  GPU path is the `opencl` extra via Mesa rusticl/Clover — the Linux analog
  of the measured Radeon runs under macOS.
- **sqlite-vec**: manylinux wheel exists (still wheel-only, no sdist).
- **llama-cpp-python**: no Linux wheels, sdist only → local cmake/gcc build;
  on this GPU use the Vulkan backend (RADV/Mesa). The `molten` extra
  (MoltenVK) is the macOS-side analog.
- **CPython 3.15**: same picture as macOS — everything has cp315/abi3
  manylinux wheels (numpy, scikit-learn, pyopencl, cryptography, hypothesis)
  except **ormsgpack**, which needs the identical 2-file PyO3 0.28 patch; on
  Arch that rebuild is trivial (native gcc + cargo, no SDK issue).
- **JIT / free-threading**: Linux x86_64 is CPython's primary JIT target
  (+7–12% geometric mean), and free-threaded manylinux wheels are published
  more widely than macOS ones.

---

## Topic: CPython version support

| Version | Status | Evidence (2026-10-01) |
| --- | --- | --- |
| 3.14.x | **Current runtime** (`requires-python >=3.14.5`) | full gate green: 303 tests, ruff, ty |
| 3.15.0rc2 | **Fully working** (needs the local ormsgpack wheel, see next topic) | 102 repo files compile; full dep tree compiles; `import swarm_sdk` + langgraph + langchain clean; 16/16 laziness + swarm-coordination tests pass |
| free-threaded 3.14/3.15t | Code ready, wheels lag | `parallel_cap()` widens 8→32 when the GIL is off (`src/swarm_sdk/execution/concurrency.py`); C-extension `t`-build wheels for pydantic-core/onnxruntime are the remaining lag |

Notes:

- The single 3.15 test failure ever observed was a **cold-start wall-clock
  flake** in `test_independent_steps_run_concurrently` (budget
  `3 * DELAY_S`), only on the first combined run; clean on every rerun.
- 3.15 runtime facts relevant here: generational GC restored (3.14's
  incremental GC reverted), mimalloc default in free-threaded builds,
  hierarchical per-module import locks, `TaskGroup.cancel()` (new),
  `bytearray.take_bytes`, builtin `frozendict`/`sentinel`, PEP 810 lazy
  imports, JIT (+7–12%), `profiling.sampling`.

---

## Topic: the ormsgpack / PyO3 blocker on 3.15 (and its fix)

ormsgpack 1.12.2 (pulled by `langgraph-checkpoint 4.2.0`) pins
**PyO3 ^0.27.2, which hard-caps at CPython 3.14**. Facts:

- No cp315 wheels exist and `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` does
  **not** apply: it only works for crates built with the `abi3` feature;
  ormsgpack is version-specific. Verified failing identically via uv (3x)
  and pip (1x).
- Working patch (two files in the sdist, verified producing a
  `cp315-macosx_10_12_x86_64` wheel that round-trips packb/unpackb):
  1. `Cargo.toml`: `pyo3 = { version = "^0.28" ... }` and
     `pyo3-build-config = { version = "^0.28" }`
  2. `src/ffi/cpython/mod.rs`: pyo3 0.28 dropped the private-symbol
     re-exports; re-declare them directly —

     ```rust
     extern "C" {
         fn _PyDict_NewPresized(len: Py_ssize_t) -> *mut PyObject;
         fn _PyDict_SetItem_KnownHash(
             mp: *mut PyObject, key: *mut PyObject,
             item: *mut PyObject, hash: Py_hash_t,
         ) -> c_int;
     }
     ```

  Build (8 s release build, cached pyo3 0.28 deps):

  ```bash
  uvx maturin build --release --interpreter /path/to/python3.15 --out /tmp/wheels315
  ```

- Local artifact kept at `/tmp/wheels315/ormsgpack-1.12.2-cp315-cp315-macosx_10_12_x86_64.whl`.
- Reproducing the 3.15 environment:

  ```bash
  CC=/usr/bin/clang CXX=/usr/bin/clang++ CFLAGS= LDFLAGS= \
  UV_PROJECT_ENVIRONMENT=/tmp/swarm-venv315 uv sync --python 3.15.0rc2 \
      --find-links /tmp/wheels315
  # uv still prefers the registry sdist at equal version; finish with:
  uv pip install --python /tmp/swarm-venv315/bin/python /tmp/wheels315/ormsgpack-*.whl
  ```

- Permanent fix is upstream: the same two-file patch as an ormsgpack PR.
- Failed-workaround note: `uv sync --no-install-package ormsgpack` still
  builds the sdist for metadata, so it does not dodge the build.

---

## Topic: dependency build-toolchain map

Verified 2026-10-01 against PyPI metadata for every direct dependency in
`pyproject.toml` (core + all extras, 54 packages). "3.15 wheel" = cp315 or
abi3 wheel for macOS x86_64 (installs without building).

### Rust (Maturin/pyo3)

| Package | Source build | 3.15 wheel |
| --- | --- | --- |
| orjson | ✔ | ✔ |
| tiktoken | ✔ | ✔ |
| ruff, ty | ✔ | n/a — shipped as `py3-none-macosx` binaries |
| cryptography (jupyter) | ✔ (Rust + toolchain) | ✔ abi3 |
| pydantic-core (transitive, pydantic) | ✔ | ✔ |
| ormsgpack (transitive, langgraph) | ✔ **after the patch above** | ✘ local wheel only |
| watchfiles, uuid-utils, rpds-py (transitive) | ✔ | ✔ |

### Rust (other harness)

- **tokenizers** — setuptools-rust; abi3 wheels (installs on 3.15).
- **polars** — now a pure loader wheel + Rust runtime wheels (no local build).
- **hypothesis** — since 6.168 ships a compiled `cp310-abi3` extension
  (installs on 3.15 without building).
- **taplo** — Rust binary shipped as ready-made platform wheel.

### Meson (meson-python; needs ninja)

- **numpy** ✔ sdist, cp315 ✔ · **scikit-learn** ✔ sdist, cp315 ✔

### C / Cython (setuptools; compiles with `CC=/usr/bin/clang`)

PyYAML ✔ (pure fallback exists) · aiohttp ✔ (+ multidict/yarl/frozenlist/
propcache) · uvloop ✔ cp315 ✔ · grpcio ✔ · grpcio-tools ✔ · selectolax ✔ ·
pyopencl ✔ cp315 ✔ (OpenCL headers) · llama-cpp-python ✔ (heavy C/C++ cmake)
· zstandard ✔ (transitive, langgraph)

### C/C++ — wheel-only, **cannot compile from PyPI materials**

| Package | Why |
| --- | --- |
| sqlite-vec | no sdist at all; wheel-only |
| faiss-cpu | no sdist; abi3 wheel ✔ works on 3.15 |
| faiss-gpu | no sdist; Linux + CUDA wheels only |
| onnxruntime / onnxruntime-gpu | no sdist; 1.30 dropped macOS x86_64 wheels (hence the pyproject markers) |

### C with pure fallback

- **protobuf** — upb C wheels + pure-Python fallback (works everywhere).

### Pure Python (28 packages — nothing to compile)

langchain, langgraph, langgraph-swarm, pydantic, pydantic-settings, fastapi,
uvicorn, httpx, httpx2, h2, requests, sympy, fastembed, transformers,
qdrant-client, mem0ai, trafilatura, beautifulsoup4, pytest, pytest-asyncio,
opentelemetry-api/sdk/exporter-otlp-proto-http/instrumentation-fastapi/
instrumentation-httpx, prometheus-client, ipykernel, jupyter-ai, notebook, pip

---

## Topic: 3.15 features already adopted / roadmap

Adopted (version-neutral, verified by `Agents/benchmark/tests/test_import_laziness.py`):

- Lazy imports at every heavy site (`core/swarm.py`, `models/chat.py`,
  `prompting/budget.py`, `serving/http.py` lazy `app`): **−58.93% cold import**
  (1,636 ms → 672 ms, see `Tasks/cold_import/`). These sites convert to literal
  PEP 810 `lazy import` mechanically once 3.15 is the floor.
- TaskGroup fail-fast waves in `bounded_gather` (`models/selection.py`):
  cancelled siblings burn **300 → 0 tokens** (`Tasks/wave_fail_fast/`); 3.15's
  `TaskGroup.cancel()` enables explicit budget-abort on top.

Not yet adopted (candidates, 3.15-only):

- `lazy import` syntax (blocked on 3.15 floor), builtin `frozendict`/
  `sentinel`, `TaskGroup.cancel()` for budget aborts, `bytearray.take_bytes`
  for the WebSearch crawl cap, `profiling.sampling` for production profiling,
  JIT build (`--experimental-jit`, +7–12%) and the free-threaded build.

---

## Topic: measured WebSearch pipeline wins (toolchain-adjacent)

Verified 2026-10-01 in the `worktree/websearch` branch, 64/64 tests:

- shared `httpx.Client` (+ HTTP/2 via `h2`, HTTP/1.1 fallback) — connection
  reuse across all searcher APIs and crawls
- shared `ThreadPoolExecutor` (no per-query thread spawn)
- `providers.yaml` cached by (path, mtime, size): **7.5 ms → 0.15 ms per call**
- `default_fetch` streams and caps bodies at `crawl.max_bytes` (bounded RAM)
- per-thread Chromium reuse in `fetch_playwright` (was: launch per URL)
- per-(searcher, query) TTL cache, opt-in via `run_pipeline`/`agent_tools`
  (cached hits report `api_tokens = 0`)
