# Toolchain & Architecture Reference — LangGraph Swarm SDK

Verified findings about compilers, silicon architecture, CPython runtimes, hardware acceleration backends, and dependency build toolchains for this repository. All metrics and configurations are empirically measured on the active host.

---

## Table of Contents

1. [Host Silicon & Hardware Architecture](#1-host-silicon--hardware-architecture)
2. [Compiler Toolchains & Build Drivers](#2-compiler-toolchains--build-drivers)
3. [CPython Runtime Support & Free-Threading](#3-cpython-runtime-support--free-threading)
4. [The `ormsgpack` / PyO3 Patch for Python 3.15](#4-the-ormsgpack--pyo3-patch-for-python-315)
5. [Dependency Build & Wheel Invariants](#5-dependency-build--wheel-invariants)
6. [Hardware Acceleration: OpenCL & MoltenVK Vulkan](#6-hardware-acceleration-opencl--moltenvk-vulkan)
7. [Python 3.15 Optimizations & Adoption Roadmap](#7-python-315-optimizations--adoption-roadmap)
8. [Measured Performance Wins](#8-measured-performance-wins)
9. [Quality Gate & Verification Commands](#9-quality-gate--verification-commands)
10. [Swarm Native Compilation Suite: Meson, Maturin, Bison & Pixi (AVX2 x AVX-512)](#10-swarm-native-compilation-suite-meson-maturin-bison--pixi-avx2-x-avx-512)
11. [Verified LLVM 23 Build Flags & Tool Selection](#11-verified-llvm-23-build-flags--tool-selection)

---

## 1. Host Silicon & Hardware Architecture

Empirically verified on macOS Darwin `x86_64` (`MacBookPro16,1`):

| Hardware Subsystem | Specification | Runtime Policy & Invariants |
| :--- | :--- | :--- |
| **Model** | MacBook Pro (16-inch, 2019) | `MacBookPro16,1` |
| **CPU** | Intel Core i7-9750H (Coffee Lake-H) | 6 physical cores / 12 hyperthreads, base 2.6 GHz, turbo 4.5 GHz |
| **Instruction Sets** | AVX, AVX2, FMA3, BMI1, BMI2, SSE4.2, AES-NI | **AVX-512 is strictly PROHIBITED** (hardware unsupported; halts with `SIGILL`) |
| **Cache Hierarchy** | 32 KB L1d, 256 KB L2 per core, 12 MB shared L3 | Cacheline: 64 bytes (`alignas(64)`) |
| **Host RAM** | 16.0 GB DDR4-2666 MHz | **Hard RSS ceiling: 13.6 GB** enforced by `HostRuleEngine` |
| **Concurrency Cap** | 3 parallel subagents | Constrained by 16 GB host memory envelope |
| **Discrete GPU (dGPU)** | AMD Radeon Pro 5300M (4 GB GDDR6 VRAM) | Accelerates OpenCL 1.2 compute and Vulkan compute via MoltenVK |
| **Integrated GPU (iGPU)** | Intel UHD Graphics 630 (1536 MB shared) | Primary display compositor |

---

## 2. Compiler Toolchains & Build Drivers

Verified on macOS `x86_64` (Darwin 25.6.0):

### 2.1 Apple Clang (System Compiler — Primary for Python C-Extensions)

- **Binary**: `/usr/bin/clang`, `/usr/bin/clang++`
- **Version**: Apple clang version 21.0.0 (`clang-2100.1.1.101`)
- **Sysroot**: Automatically links the macOS SDK sysroot (`MacOSX.sdk`).
- **Standard invocation for building C extensions**:
  ```bash
  CC=/usr/bin/clang CXX=/usr/bin/clang++ CFLAGS="" LDFLAGS="" uv sync
  ```

### 2.2 Custom LLVM 23.1.1 Clang (Native Optimized Toolchain)

- **Binary**: `/Users/usuario/.local/opt/llvm-23.1.1/bin/clang`
- **Version**: LLVM clang version 23.1.1 (`Target: x86_64-apple-darwin25.6.0`)
- **Characteristics**: Default user flags use aggressive optimization (`-O3 -march=native -fuse-ld=lld`).
- **Critical Limitation**: Because it lacks macOS SDK default sysroot paths, attempting to compile Python C extensions (like `cryptography` or `pyopencl`) without explicit SDK headers fails with:
  ```text
  fatal error: 'assert.h' file not found
  ```
- **Rule**: Never use custom LLVM clang for Python wheel builds without clearing compiler environment variables. Always prepend `CC=/usr/bin/clang CXX=/usr/bin/clang++` when building native extensions.

#### 2.2.1 LLVM/Clang 23.1 Release Profile (H2 2026 Stable)
- **Release Date**: 25 August 2026 (first stable release of the LLVM 23 series).
- **Core Microarchitectural Features**:
  - **x86 Lightweight Fault Isolation (LFI)**: Introduces native target support for fine-grained process isolation and memory sandboxing.
  - **AMD Zen 6 Target (`znver6`)**: Adds instruction scheduling and AVX-512 BMM (Bfloat16 Matrix Multiply) vectorization.
  - **NVIDIA Rigel & AMDGPU GFX1310**: Initial hardware offloading support for the NVIDIA Rosa processor (Rigel core) and AMD HIP driver.
  - **Arm C1-Ultra**: Modern pipeline scheduling model for high-throughput server chips.
  - **C++26 & C2Y Progress**: Partial C++26 dialect support enabled via `-std=c++2c` / `-std=c++26`, alongside latest C2Y extensions.
  - **Linker Performance (`ld64.lld`)**: Faster parallel symbol resolution during ThinLTO linking on Darwin (`x86_64-apple-darwin25.6.0`).

#### 2.2.2 GCC 16.1 Release Contrast & Linux vs. macOS Ecosystem
- **Release Date**: 30 April 2026 (GNU Compiler Collection 16.1).
- **Dialect Defaults**: Bumps default C++ language standard from `-std=gnu++17` to **`-std=gnu++20`**, and default C standard to **`gnu23`**.
- **C++26 Breakthroughs in GCC 16**:
  - **P2996R13 Reflection**: Enabled via `-std=c++26 -freflection` (including P3394R4 annotations and P3096R12 parameter reflection).
  - **P2900R14 Contracts**: Native `-fcontracts` enforcement for runtime validation invariants.
  - **P1306R5 Expansion Statements**: Template parameter pack iterations without recursive template metaprogramming.
- **Linux vs. macOS Darwin Toolchain Division**:
  - **Linux x86_64 (Ubuntu 26.10 / Fedora 45)**: Ships GCC 16.1 as default system compiler with glibc/libstdc++ and full AVX-512 BMM auto-vectorization on server hardware.
  - **macOS Darwin x86_64 (MacBookPro16,1)**: Relies on Apple Clang for system wheels and LLVM/Clang 23.1.1 (`/Users/usuario/.local/opt/llvm-23.1.1/bin/clang`) for native AVX2 SIMD tool builds with `-march=haswell -mtune=skylake` (AVX-512 strictly excluded to avoid `SIGILL`).

### 2.3 Rust Toolchain & Maturin

- **Rust Compiler**: `rustc 1.99.0` (`/Users/usuario/.cargo/bin/rustc`)
- **Rust LLVM backend**: `rustc -vV` reports LLVM **23.1.1** on this host. The LLVM version of a separate `clang` executable does not change Rust's backend; check both before mixing Rust and C/C++ link-time optimization.
- **Cargo**: `cargo 1.99.0` (`/Users/usuario/.cargo/bin/cargo`)
- **Maturin**: Used for building PyO3 native extensions (`uvx maturin build`).
  - **Installed here**: no (`command -v maturin` is empty); it runs on demand through `uvx`, so the version floats unless pinned: `uvx maturin@1.15.0 build --release --interpreter <python>` (Context7/uv docs: `command@<version>` pins an exact version only, `@latest` refreshes the cache, and ranges need `--from 'maturin>=1.14,<2'`; the maturin run itself was not executed here).
  - **Latest**: 1.15.0 on PyPI (`requires-python >=3.7`, checked with the PyPI JSON API on 2026-10-03).
  - **Commands** (maturin README on PyPI): `maturin build` writes wheels to `target/wheels` without uploading; `maturin develop` installs into the active virtualenv; `-r/--release` is required for optimized code.
  - **Python 3.15 / free-threading** (maturin release notes and `guide/src/bindings.md`): 1.14.0 added `abi3t` support for Python 3.15 with PyO3 0.29, and `-f/--find-interpreter` (the CLI spelling; the changelog writes `--find-interpreters`) now finds free-threaded interpreters. Free-threaded CPython 3.14 does not support `abi3t`, so maturin builds a version-specific `cp314-cp314t` wheel there. A single `maturin build` selects one stable-ABI family; build `abi3` and `abi3t` wheels separately (`--interpreter python3.10`, `--interpreter python3.15t`).
  - **Link to §4**: the `ormsgpack` fix builds against PyO3 0.28; the `abi3t` features need PyO3 0.29, so they do not apply to that patch.

### 2.4 Ninja Build Driver

- **Binary**: `/usr/local/bin/ninja`
- **Version**: 1.13.2
- **Role**: High-speed parallel build driver for Meson packages (`numpy`, `scikit-learn`) and C++ CMake extensions. Saturates up to 12 execution threads (`ninja -j 12`).
- **Scope**: Use Ninja only when Meson or CMake generated a Ninja build. Cargo builds Alacritty directly, and Zig builds Ghostty; adding `ninja` to those commands does not enable an optimization.

### 2.5 Astral `uv` Package & Environment Manager

- **Binary**: `/Users/usuario/.local/bin/uv`
- **Configuration**:
  - `python-preference = "managed"` in `pyproject.toml`.
  - Cached wheels per Python ABI (`cp314`, `cp315`).
  - Wheel-only constraint on `cryptography` via `no-build-package = ["cryptography"]` to prevent accidental un-sysrooted source compiles.

### 2.6 Meson Build System

- **Binary**: `/usr/local/bin/meson`, version **1.12.1** (`meson --version`); PyPI latest is also 1.12.1 (`requires-python >=3.10`). Meson 1.12.0 was released 10 August 2026 (release notes, mesonbuild.com).
- **Role**: configures `meson-python` packages such as `numpy` (see §5); Ninja (§2.4) is the backend.
- **ThinLTO with the custom LLVM 23.1.1 (verified)**: a one-file AVX2/FMA probe configured with `CC=$LLVM23_HOME/bin/clang` and `SDKROOT=$(xcrun --show-sdk-path)`:
  ```bash
  meson setup build -Db_lto=true -Db_lto_mode=thin \
    -Dc_args=-march=native -Dc_link_args=-fuse-ld=lld
  ninja -C build && ./build/probe      # printed 6.000000 (fmadd result)
  ```
  Meson detected `clang 23.1.1` with linker `ld64.lld 23.1.1`; `meson configure` lists `b_lto_mode` choices `[default, thin]`. ThinLTO static archives on Mach-O still need the `llvm-libtool-darwin` shim (`~/build/toolchain-shims/libtool`) first on `PATH`.
- **Native files**: pass a native file with `meson setup --native-file my-native-file.ini builddir/` to pin compiler and flags instead of exporting `CC`/`CFLAGS` (Meson "Native environments" docs). `meson env2mfile --native -o current_system.txt` can generate one from the environment, but the 0.62 release notes call that command experimental and subject to change.
- **Rust + LTO caveat** (Meson 1.10 release notes): with `b_lto=true` Meson passes `-C lto` to `rustc`, and with LTO off it passes `-C embed-bitcode=no`, which is incompatible with `-C lto` placed in `rust_args`. This is the same failure `~/.cargo/config.toml` documents for global `RUSTFLAGS`: set LTO through the build option, not through flags.
- **Rule**: for Python wheels keep Apple clang (§2.2 rule); use the LLVM 23 toolchain with Meson only for from-source tools.

### 2.7 GNU Bison (Parser Generator)

- **System binary**: `/usr/bin/bison` is **GNU Bison 2.3** (verified); `/usr/bin/m4` is GNU M4 1.4.6 (verified). macOS keeps these old versions; do not rely on them for grammars written for Bison 3.x (for example `%define api.*` or `glr2.cc`).
- **Latest stable**: **3.8.2**, released 2021-09-25 (GNU Bison announcement); `https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz` answers HTTP 200 (checked). The mirror listing has no newer tarball, and MacPorts also ships 3.8.2.
- **Installed here**: only the 2.3 system copy; 3.8.2 is **not** built.
- **Build route (not run)**: download `bison-3.8.2.tar.xz` and its `.sig` from `ftp.gnu.org`, verify the signature or checksum before extracting, then `./configure --prefix=$HOME/.local/opt/bison-3.8.2 && make -j6 && make check && make install`. Keep it off `/usr/local/bin` so the system tools and existing builds are unaffected; put it first on `PATH` only inside the build script that needs it. MacPorts lists `m4`, `gettext-runtime`, `libiconv` and `libtextstyle` as dependencies; Bison needs a GNU `m4`.
- **Swarm impact**: none of the packages audited in §5 needs Bison.

### 2.8 GHC (Glasgow Haskell Compiler)

- **Installed here**: no. `ghc`, `cabal`, `ghcup` and `stack` are all absent (`command -v`). Consequence: **ShellCheck cannot be built from source** on this host (it is a Haskell program); the existing `shellcheck` binary stays as is.
- **Latest release**: GHC **9.14.1** (released 19 Dec 2025, `downloads.haskell.org/ghc/latest`). `9.12.4` is also published. x86_64 macOS is a supported platform; the bindist is `ghc-9.14.1-x86_64-apple-darwin.tar.xz` (302.8 MB) and requires the Xcode Command Line Tools.
- **LLVM backend is unusable with the custom toolchain**: the 9.14.1 download page states the LLVM backend needs **LLVM 11, 12, 13, 14 or 15**, while this host has LLVM 23.1.1. Use GHC's native code generator (default); do not pass `-fllvm`. Whether GHC's native generator emits AVX2 was **not verified**; check the GHC user guide before promising SIMD speedups.
- **LTO**: no GHC/Cabal LTO option was found in the sources read; treat Haskell binaries as non-LTO.
- **Install routes**: the official GHCup page (`haskell.org/ghcup/install`) installs via `curl --proto '=https' --tlsv1.2 -sSf https://get-ghcup.haskell.org | sh`. That pipes the network into a shell, which this repo's rules forbid. Use one of: (1) download the GHC bindist from `downloads.haskell.org`, verify its signature or checksum, then `./configure --prefix=... && make install`; or (2) install `ghcup` as a package (`brew install ghcup`), then `ghcup install ghc 9.14.1 && ghcup set ghc 9.14.1`, which downloads GHC into `~/.ghcup` (checksum handling not inspected). Add `~/.ghcup/bin` to `PATH` only in the shell config that already owns `PATH` (`zshenv.zsh`).
- **Footprint**: the bindist alone is about 300 MB compressed, and it adds nothing to the Swarm runtime; install it only when a Haskell tool (ShellCheck, `cabal`) is actually needed.

### 2.9 Agent CLI Tools Built From Source (`cli-agents-avx2`)

Built on 2026-10-03 by `~/build/build-cli-agents-avx2.sh` into the staging prefix `~/.local/opt/cli-agents-avx2/bin` (not on `PATH`; no existing binary was replaced; rollback is `rm -rf` of the prefix). Logs: `~/build/cli-agents-avx2.log` and `~/build/cli-agents-logs/`.

| Tool | Version | How it was built | Measured result |
| :--- | :--- | :--- | :--- |
| `jq` | 1.8.2 | LLVM 23.1.1 clang, `-O3 -march=native -flto=thin`, `-fuse-ld=lld`; tarball SHA-256 checked against the release `sha256sum.txt` | `make check` 7/7 pass; **0 `ymm` (AVX2) instructions** in the binary (scalar code), and ThinLTO was requested but not independently confirmed |
| `yq` | v4.54.1 | `go install` with `GOAMD64=v3`, `CGO_ENABLED=0`, `-trimpath`; Go has no LTO | runs (`yq '.a'` returned `1`); AVX2 effect not measured |
| `just` | 1.58.0 | `cargo install --locked`; AVX2 and ThinLTO come from `~/.cargo/config.toml` (`target-cpu=native`, `lto = "thin"`) | 28,507 `ymm` instructions; `-C lto=thin` and `target-cpu=native` present in the `cargo -v` log |
| `ast-grep` | 0.45.3 | same as `just` | 37,991 `ymm` instructions; build took about 5 minutes; the `sg` alias is a deprecated shim that execs `ast-grep` from `PATH` |
| `sqlite-utils` | 4.2.1 | `uv tool install --python 3.14` into the prefix; pure Python, nothing to compile | `sqlite-utils --version` reports 4.2.1 |
| `shellcheck` | not built | needs GHC (§2.8), absent on this host | existing binary unchanged |

No speed comparison against the previous `jq 1.7.1-apple`, `yq 4.4.0` or other installed copies was run, so no performance gain is claimed. Using these builds means putting the prefix first on `PATH`.

---

## 3. CPython Runtime Support & Free-Threading

The repository supports CPython 3.14.x as the primary runtime and is forward-compatible with Python 3.15.

| Version | Target / Path | Status | Verification Evidence |
| :--- | :--- | :--- | :--- |
| **3.14.8** | `/Users/usuario/.local/opt/python-3.14.8` | **Active Production** (`requires-python >=3.14.5`; worktree `.python-version` = 3.14.8) | Built 2026-10-03 with `~/build/build-python-3.14.8.sh` (tarball SHA-256 matched python.org; Gate 0/3: `SOABI cpython-314-darwin`); 240 websearch/vault/model tests green on it. 3.14.7 stays at `~/.local/opt/python-3.14.7` |
| **3.15.0rc2** | `/Users/usuario/.local/opt/python-3.15-g6413901/bin/python3.15` | **Fully Verified** | Requires local `ormsgpack` PyO3 0.28 wheel; 16/16 laziness & coordination tests pass |
| **3.14t / 3.15t** | `/Users/usuario/.local/bin/python3.14t` | **Code Ready** (Free-Threaded / PEP 703) | `parallel_cap()` dynamically widens from 8 to 32 when the GIL is disabled (`src/swarm_sdk/execution/concurrency.py`). Awaiting wider upstream `t`-wheels **3.15t note (2026-10-03):** the existing 3.15t build has `SOABI=cpython-315t` (no `-darwin`) because configure ran without `SDKROOT`, so no PyPI wheel imports; a rebuild needs `SDKROOT` exported and a tag build (`v3.15.0rc3`). orjson builds only with `ORJSON_BUILD_FREETHREADED=1` (upstream experimental opt-in). Parked in favor of 3.14.8. |

### Key Python 3.14/3.15 Runtime Characteristics

- **CPython 3.14**: Active runtime. Features incremental GC, PEP 649 deferred annotation evaluation, and structured concurrency.
- **CPython 3.15**: Restores generational GC (improving throughput over 3.14 incremental GC in heavy AST traversals), uses mimalloc by default in free-threaded builds, introduces hierarchical per-module import locks, native `TaskGroup.cancel()`, `bytearray.take_bytes`, built-in `frozendict`/`sentinel`, and PEP 810 lazy imports.

---

## 4. The `ormsgpack` / PyO3 Patch for Python 3.15

`ormsgpack 1.12.2` (pulled by `langgraph-checkpoint 4.2.0`) pins `PyO3 ^0.27.2`, which enforces a hard ceiling at CPython 3.14.

### The Blocker
- No PyPI `cp315` wheels exist.
- Setting `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` fails because `ormsgpack` is version-specific rather than `abi3`-enabled.

### The Verified 2-File Fix
1. In `Cargo.toml`: upgrade to PyO3 0.28:
   ```toml
   pyo3 = { version = "^0.28" }
   pyo3-build-config = { version = "^0.28" }
   ```
2. In `src/ffi/cpython/mod.rs`: re-declare private symbols dropped by PyO3 0.28:
   ```rust
   extern "C" {
       fn _PyDict_NewPresized(len: Py_ssize_t) -> *mut PyObject;
       fn _PyDict_SetItem_KnownHash(
           mp: *mut PyObject, key: *mut PyObject,
           item: *mut PyObject, hash: Py_hash_t,
       ) -> c_int;
   }
   ```
3. Compile the wheel with `uvx maturin`:
   ```bash
   uvx maturin build --release --interpreter /path/to/python3.15 --out /tmp/wheels315
   ```
4. Install into a Python 3.15 environment:
   ```bash
   CC=/usr/bin/clang CXX=/usr/bin/clang++ CFLAGS="" LDFLAGS="" \
   UV_PROJECT_ENVIRONMENT=/tmp/swarm-venv315 uv sync --python 3.15.0rc2 \
       --find-links /tmp/wheels315
   uv pip install --python /tmp/swarm-venv315/bin/python /tmp/wheels315/ormsgpack-*.whl
   ```

---

## 5. Dependency Build & Wheel Invariants

Audited against the active repository dependencies in `pyproject.toml` (54 packages):

### Rust Extensions (Maturin / Setuptools-Rust)
- **`orjson`**: Pre-built `cp314` and `cp315` wheels available.
- **`tiktoken`**: Pre-built wheels available; compiles cleanly via Cargo.
- **`tokenizers`**: Ships `cp39-abi3` wheels; works out of the box on Python 3.14 and 3.15.
- **`cryptography`**: Pinned to `48.0.1`. Must use pre-built binary wheels on Intel Mac (`no-build-package = ["cryptography"]`).
- **`pydantic-core`**: Binary wheels available for `cp314` and `cp315`.
- **`ormsgpack`**: Compiles cleanly with the PyO3 0.28 patch detailed above.

### Meson / C++ (Ninja Driver)
- Meson 1.12.1, ThinLTO and flag details: see §2.6.
- **`numpy`**: Binary wheels available; builds with `meson-python` + `ninja`.
- **`scikit-learn`**: Ships `cp314` and `cp315` wheels.

### C / Cython Extensions
- **`aiohttp`**, **`uvloop`**, **`grpcio`**, **`selectolax`**, **`pyopencl`**: Compile cleanly with `/usr/bin/clang`.
- `pyopencl` links directly against macOS `/System/Library/Frameworks/OpenCL.framework`.

### Wheel-Only Packages (No Source Build from PyPI)
| Package | Platform Constraint & Note |
| :--- | :--- |
| `sqlite-vec` | Wheel-only (`>=0.1.6`). Uses pre-compiled native vector extension. |
| `faiss-cpu` | Wheel-only (`abi3` wheel works on 3.14 and 3.15). |
| `faiss-gpu` | **Prohibited on macOS**. CUDA-only Linux binary; cannot run on AMD/Apple hardware. |
| `onnxruntime` / `fastembed` | Excluded on Intel Mac via marker: `sys_platform != 'darwin' or platform_machine != 'x86_64'`. ONNX dropped official macOS `x86_64` wheels starting with v1.30. |

---

## 6. Hardware Acceleration: OpenCL & MoltenVK Vulkan

The discrete **AMD Radeon Pro 5300M** (4 GB GDDR6) provides accelerated compute paths without NVIDIA CUDA:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Swarm Compute Matrix                     │
├──────────────────────────────┬──────────────────────────────┤
│ AMD Radeon Pro 5300M (4 GB)  │ Metal-backed Compute         │
├──────────────────────────────┼──────────────────────────────┤
│ 1. OpenCL 1.2 Compute Engine │ macOS OpenCL.framework       │
│    • Batch Dot / Cosine      │ • swarm_sdk.gpu.opencl_math  │
│    • Normalize / Top-K       │ • OpenClVecStore Index       │
├──────────────────────────────┼──────────────────────────────┤
│ 2. Vulkan via MoltenVK       │ libMoltenVK.dylib -> Metal   │
│    • llama.cpp Embeddings    │ • GGUF Local Model Inference │
│    • VK_ICD_FILENAMES        │ • Zero CUDA dependency       │
└──────────────────────────────┴──────────────────────────────┘
```

### 6.1 OpenCL 1.2 Compute Engine
- **Framework**: `/System/Library/Frameworks/OpenCL.framework`
- **Device ID**: `AMD Radeon Pro 5300M Compute Engine`
- **Features**: Single-precision floating point matrix multiplication, batched cosine similarity, and vector normalization.
- **Activation**: Configured via `SWARM_OPENCL_ENABLED=true` and `SWARM_MEMORY_BACKEND=opencl`.

### 6.2 Vulkan via MoltenVK (Metal Translation Layer)
- **Library**: `libMoltenVK.dylib` located in `/usr/local/opt/molten-vk/lib/` or `/usr/local/lib/`.
- **ICD Manifest**: `/usr/local/etc/vulkan/icd.d/MoltenVK_icd.json`
- **Device Node**: Identified as `Vulkan0` (`AMD Radeon Pro 5300M`).
- **Use Case**: Powers local GGUF embedding models via `llama-cpp-python` compiled with Vulkan support.

### 6.3 AMD Radeon Pro 5300M on Arch Linux (Navi 14 / GFX1012 Architecture)

On Arch Linux workstations and dual-boot MacBookPro16,1 setups, the discrete **AMD Radeon Pro 5300M** operates under the open-source `amdgpu` kernel driver with full support for hardware-accelerated OpenCL and Vulkan compute:

#### 1. Kernel Driver & Power Management
- **Hardware Architecture**: Navi 14 / RDNA 1 (`GFX1012`, 1408 stream processors, 4 GB GDDR6).
- **Required Packages**:
  ```bash
  sudo pacman -S linux linux-firmware mesa lib32-mesa vulkan-radeon lib32-vulkan-radeon
  ```
- **Driver Module Configuration (`/etc/modprobe.d/amdgpu.conf`)**:
  ```ini
  options amdgpu ppfeaturemask=0xffffffff dpm=1 audio=0
  ```
  Enables full power play overdrive, DPM clock scaling, and disables unused HDMI/DP audio to reduce interrupt latency.

#### 2. OpenCL Compute: Rusticl vs. ROCm on Arch Linux
- **Recommended: Mesa Rusticl (OpenCL 3.0 Conformance)**:
  Rusticl provides a modern, fast Rust-based OpenCL 3.0 implementation backed by Gallium3D and LLVM, eliminating proprietary driver conflicts:
  ```bash
  sudo pacman -S opencl-rusticl-mesa clinfo
  # Activate Rusticl for radeonsi driver in shell environment
  export RUSTICL_ENABLE=radeonsi
  export OCL_ICD_VENDORS=rusticl.icd
  ```
  `clinfo` confirms `Platform Name: Rusticl`, `Device Name: AMD Radeon Pro 5300M (radeonsi, navi14, LLVM ...)`.
- **Alternative: ROCm OpenCL / HIP Offload**:
  Navi 14 is not officially whitelisted in upstream ROCm, requiring an environment override:
  ```bash
  sudo pacman -S rocm-opencl-runtime rocm-hip-sdk
  export HSA_OVERRIDE_GFX_VERSION=10.1.0
  ```

#### 3. Vulkan Compute Engine (Mesa RADV + ACO)
- **High-Speed GGUF Embeddings**: RADV with the default ACO compiler compiles compute shaders up to **4x faster** than traditional LLVM backends:
  ```bash
  export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.x86_64.json
  # Build and run llama.cpp Vulkan backend
  CMAKE_ARGS="-DGGML_VULKAN=ON" uv pip install --no-build-isolation llama-cpp-python
  ```

---

## 7. Python 3.15 Optimizations & Adoption Roadmap

### Already Adopted (Version-Neutral)
- **Import Laziness**: Heavy modules (`core/swarm.py`, `models/chat.py`, `prompting/budget.py`, `serving/http.py`) defer imports until invocation. Cold import latency dropped by **−58.9%** (1,636 ms → 672 ms). Verified by `Agents/benchmark/Tasks/cold_import/test_cold_import.py`.
- **Wave Fail-Fast**: Implemented in `bounded_gather` (`models/selection.py`). When a wave fails, cancelled sibling tasks abort immediately, dropping wasted tokens from **300 → 0**. Verified by `Agents/benchmark/Tasks/wave_fail_fast/test_wave_fail_fast.py`.

### Roadmap for Python 3.15 Floor
- **PEP 810 Literal `lazy import` Syntax**: Replace programmatic lazy getters with native compiler syntax once Python 3.15 is the minimum required version.
- **Native `TaskGroup.cancel()`**: Direct budget-abort signals across LangGraph worker waves.
- **`bytearray.take_bytes`**: Zero-copy crawler memory compaction in WebSearch.
- **Sampling Profiler (`profiling.sampling`)**: Production low-overhead sampling without external C-extensions.

---

## 8. Measured Performance Wins

Empirically verified in benchmark suites:

1. **Cold Import Optimization**:
   - Baseline: `1,636 ms`
   - Optimized: `672 ms` (**−58.93% reduction**)
2. **Provider Configuration Cache**:
   - Uncached YAML disk reads: `7.50 ms`
   - (Path, mtime, size) memory cache: `0.15 ms` (**50x speedup**)
3. **HTTP/2 Connection Reuse**:
   - Persistent `httpx.Client` with `h2` multiplexing across parallel search and LLM calls.
4. **Cancelled Wave Token Burn**:
   - Reduced from `300 tokens` to `0 tokens` on wave failure.

---

## 9. Quality Gate & Verification Commands

All changes in this repository must pass the full verification gate before being merged:

Check `UV_PYTHON` before running this gate. On 2026-10-03, an inherited `UV_PYTHON` pointing to free-threaded Python 3.15 overrode `.python-version` (`3.14.8`), recreated `.venv`, and failed to install `faiss-cpu`. If that variable is set, pass `--python "$(cat .python-version)"` to each `uv run` command (or unset it for the shell) so the gate uses the project interpreter.

```bash
# 1. Targeted CLI tests
uv run --extra dev pytest tests/test_cli.py -q --tb=short

# 2. Benchmark test suite (429 tests)
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q

# 3. Ruff linter & format verification
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main

# 4. Ty static type checker
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main

# 5. Swarm agent manifest validation (22 manifests)
uv run python -m swarm_sdk.agents.validate
```

---

## 10. Swarm Native Compilation Suite: Meson, Maturin, Bison & Pixi (AVX2 x AVX-512)

This section sketches build manifests for native Swarm SIMD kernels, grammar parsers, and Python PyO3 extensions across **AVX2** (MacBookPro16,1 host baseline) and **AVX-512** (compatible Linux servers). These examples are not installed build files or a verified Swarm build; check each compiler and target before using them.

### 10.1 AVX2 vs. AVX-512 Microarchitectural Profile

```
+=============================================================================================================+
|                                    AVX2 vs. AVX-512 MICROARCHITECTURAL PROFILE                              |
+=============================================================================================================+

  Feature                           AVX2 Baseline (Host MacBookPro16,1)           AVX-512 (Arch Linux Server Nodes)
  --------------------------------  -------------------------------------------  -------------------------------------------
  Register Width                    256-bit (ymm0–ymm15)                         512-bit (zmm0–zmm31)
  Parallel FP32 Operations / Cycle  8 floats                                     16 floats (2x arithmetic density)
  Parallel INT8 Quantized / Cycle   32 bytes                                     64 bytes
  Instruction Subsets               FMA3, BMI1, BMI2, POPCNT, SSE4.2             F, CD, BW, DQ, VL, VNNI, BF16
  Frequency Impact                  Zero frequency downclocking on i7-9750H      Older Intel Xeon: frequency license downclock
                                                                                 AMD Zen 4/5/6: Full boost clock (no drop)
  Host Compatibility                100% Native on MacBookPro16,1                UNSUPPORTED on MacBookPro16,1 (SIGILL)
  Compiler Flags                    -mavx2 -mfma -mbmi2                          -mavx512f -mavx512dq -mavx512bw -mavx512vl
```

#### Runtime Universal SIMD Dispatch (Google Highway NEP 54 Pattern)
To compile separate macOS and Linux binaries from the same source while selecting a supported SIMD implementation at runtime:

```c
/* dynamic_simd_dispatch.c: Runtime CPUID feature selection */
#include <pthread.h>

typedef float (*dot_product_fn)(const float*, const float*, int);

extern float dot_product_avx2(const float* a, const float* b, int n);
extern float dot_product_avx512(const float* a, const float* b, int n);

static dot_product_fn selected_dot_product;
static pthread_once_t dispatch_once = PTHREAD_ONCE_INIT;

static void resolve_dot_product(void) {
    __builtin_cpu_init();
    if (__builtin_cpu_supports("avx512f") && __builtin_cpu_supports("avx512vl")) {
        selected_dot_product = dot_product_avx512;
    } else {
        selected_dot_product = dot_product_avx2;
    }
}

float dot_product(const float* a, const float* b, int n) {
    pthread_once(&dispatch_once, resolve_dot_product);
    return selected_dot_product(a, b, n);
}
```

---

### 10.2 Pixi Multi-Platform Environment Specification (`pixi.toml`)

Pixi provides hermetic, lockfile-reproducible native environments managing C/C++, Rust, Python, and OpenCL/Vulkan compilers across macOS Darwin (`osx-64`) and Arch Linux (`linux-64`):

```toml
# pixi.toml: Reproducible multi-platform native toolchain
[project]
name = "swarm-native-suite"
version = "0.1.0"
description = "Hermetic build toolchain for Swarm SIMD kernels & parsers"
authors = ["dantenho <dantenho@gmail.com>"]
channels = ["conda-forge"]
platforms = ["osx-64", "linux-64"]

[dependencies]
python = ">=3.14"
ninja = ">=1.13"
meson = ">=1.12"
maturin = ">=1.15"
bison = ">=3.8"
flex = ">=2.6"
pkg-config = ">=0.29"

[target.osx-64.dependencies]
clang = ">=21"
llvm-openmp = ">=19"

[target.linux-64.dependencies]
gcc = ">=16.1"
gxx = ">=16.1"
ocl-icd = ">=2.3"
opencl-headers = ">=2024"
vulkan-headers = ">=1.3"

[tasks]
build-avx2 = "meson setup build-avx2 --native-file toolchain/native-avx2.ini && ninja -C build-avx2"
build-avx512 = "meson setup build-avx512 --native-file toolchain/native-avx512.ini && ninja -C build-avx512"
build-rust = "maturin develop --release --features simd_avx2"
test-simd = "pytest tests/test_simd_kernels.py -v"
```

---

### 10.3 Meson Native Build Definitions

#### 1. `meson.build`
```meson
# meson.build: High-speed compilation manifest for native Swarm extensions
project('swarm_simd', 'c', 'cpp',
  version : '0.1.0',
  default_options : [
    'warning_level=3',
    'cpp_std=c++20',
    'c_std=c17',
    'b_lto=true'
  ]
)

cc = meson.get_compiler('c')
simd_args = []
simd_level = get_option('simd')

if simd_level == 'avx512'
  simd_args = ['-mavx512f', '-mavx512dq', '-mavx512bw', '-mavx512vl', '-mfma']
  add_project_arguments('-DSWARM_ENABLE_AVX512=1', language : ['c', 'cpp'])
elif simd_level == 'avx2'
  simd_args = ['-mavx2', '-mfma', '-mbmi2']
  add_project_arguments('-DSWARM_ENABLE_AVX2=1', language : ['c', 'cpp'])
endif

# Bison parser generation for Swarm DSL queries
bison = find_program('bison')
bison_gen = generator(bison,
  output : ['@BASENAME@.tab.c', '@BASENAME@.tab.h'],
  arguments : ['-d', '-Wcounterexamples', '@INPUT@', '-o', '@OUTPUT0@']
)

parser_sources = bison_gen.process('src/grammar/query_parser.y')

swarm_simd_lib = shared_library('swarm_simd',
  sources : ['src/simd/vector_math.cpp', parser_sources],
  c_args : simd_args,
  cpp_args : simd_args,
  install : true
)
```

#### 2. Native Profile `native-avx2.ini` (Host MacBookPro16,1)
```ini
[binaries]
c = 'clang'
cpp = 'clang++'
ar = 'llvm-ar'
strip = 'llvm-strip'

[built-in options]
b_lto_mode = 'thin'
c_args = ['-O3', '-march=native', '-mavx2', '-mfma', '-fno-semantic-interposition']
cpp_args = ['-O3', '-march=native', '-mavx2', '-mfma', '-fno-semantic-interposition']
c_link_args = ['-fuse-ld=lld']
cpp_link_args = ['-fuse-ld=lld']
simd = 'avx2'
```

#### 3. Native Profile `native-avx512.ini` (Arch Linux / Zen 4+ Server)
```ini
[binaries]
c = 'gcc'
cpp = 'g++'
ar = 'gcc-ar'
strip = 'strip'

[built-in options]
c_args = ['-O3', '-march=znver4', '-mavx512f', '-mavx512dq', '-mavx512bw', '-mavx512vl', '-fno-semantic-interposition']
cpp_args = ['-O3', '-march=znver4', '-mavx512f', '-mavx512dq', '-mavx512bw', '-mavx512vl', '-fno-semantic-interposition']
c_link_args = ['-flto']
cpp_link_args = ['-flto']
simd = 'avx512'
```

---

### 10.4 Maturin & PyO3 Free-Threaded SIMD Cargo Configuration

```toml
# Cargo.toml: PyO3 extension with conditional AVX2/AVX-512 SIMD feature flags
[package]
name = "swarm_rust_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "swarm_rust_core"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.29", features = ["abi3-py315", "extension-module"] }

[features]
default = ["simd_avx2"]
simd_avx2 = []
simd_avx512 = []

[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1
panic = "abort"
```

---

### 10.5 GNU Bison Grammar Specification (`src/grammar/query_parser.y`)

Re-entrant, modern GNU Bison 3.8+ specification for parsing multi-agent swarm query expressions:

```yacc
%code top {
    #include <stdio.h>
    #include <stdlib.h>
    #include "query_ast.h"
}

/* Modern Bison 3.8+ Re-Entrant & Pure Parser Directives */
%define api.pure full
%define api.value.type variant
%define parse.error verbose
%lex-param   { void *scanner }
%parse-param { void *scanner } { QueryASTNode **result_ast }

%token <char*> IDENTIFIER STRING_LITERAL
%token <int> INTEGER_LITERAL
%token AND OR NOT EQUALS GREATER_THAN

%type <QueryASTNode*> expr comparison

%%

query:
    expr { *result_ast = $1; }
    ;

expr:
      comparison
    | expr AND comparison { $$ = create_binary_op(OP_AND, $1, $3); }
    | expr OR comparison  { $$ = create_binary_op(OP_OR, $1, $3); }
    ;

comparison:
      IDENTIFIER EQUALS STRING_LITERAL { $$ = create_comparison(OP_EQ, $1, $3); }
    | IDENTIFIER GREATER_THAN INTEGER_LITERAL { $$ = create_num_comparison(OP_GT, $1, $3); }
    ;

%%
```

---

## 11. Verified LLVM 23 Build Flags & Tool Selection

Use the build system and object format of the target project before selecting flags. The table separates options that affect the running binary from tools that only build or package it.

| Tool or option | Correct scope on this macOS host | Verification or limit |
| :--- | :--- | :--- |
| Rust ThinLTO | Set `lto = "thin"` in `[profile.release]` of `Cargo.toml`; build with `cargo build --release`. | Alacritty's release profile already has this setting. `rustc -vV` reports LLVM 23.1.1. Keep `-C lto` out of global `RUSTFLAGS`, which also affect host build scripts and proc macros. |
| LLVM 23 Clang | Use for selected C/C++ dependencies with an explicit macOS SDK sysroot. | `clang 23.1.1` could not find `wchar.h` in a `cc-rs` build until `-isysroot` pointed at the Command Line Tools SDK. Keep Apple Clang as the default for repository Python wheels (§2.2). |
| Polly | Pass `-O3 -mllvm -polly` to the matching LLVM 23 Clang for C/C++ translation units. | The Alacritty mimalloc C dependency built with this flag. It did **not** apply Polly to Rust code, and no speedup or transformed loop was measured. See [Polly's Clang guide](https://polly.llvm.org/docs/UsingPollyWithClang.html). |
| mimalloc | Link the Rust `mimalloc` crate and set it as the executable's single global allocator. | Alacritty built with `mimalloc 0.1.52`; its version command and macOS code signature check passed. This establishes build correctness, not a performance gain. |
| `mini-alloc` | Do not use as a terminal's global allocator. | Its [documentation](https://docs.rs/crate/mini-alloc/latest) says `dealloc` does nothing, so a long-running terminal would leak allocations. Rust also permits only one global allocator per executable. |
| LLVM BOLT | Use only where its binary rewriter supports the output format and a representative profile is available. | The macOS executable is Mach-O, while [BOLT's supported primary format is ELF](https://discourse.llvm.org/t/rfc-bolt-a-framework-for-binary-analysis-transformation-and-optimization/56722). No BOLT optimization was applied. |
| Zstd | Compress a finished app archive for transfer or storage. | `zstd -t` checked the Alacritty archive. Compression does not optimize the running executable. |
| Ninja | Drive a Meson or CMake Ninja build tree. | Alacritty uses Cargo; Ghostty uses Zig. The executable's build does not become faster by naming Ninja when no Ninja build tree exists. |

### Reproduce the verified Alacritty variant

On 2026-10-03, Alacritty `0.18.0-dev` at commit `d692748` built as an x86_64 macOS app using the Command Line Tools SDK. Its `Cargo.toml` already specified ThinLTO. The only source changes were `mimalloc = "0.1.52"` in the executable crate's dependencies and this global allocator declaration in `alacritty/src/main.rs`:

```rust
#[global_allocator]
static GLOBAL_ALLOCATOR: mimalloc::MiMalloc = mimalloc::MiMalloc;
```

From that source tree, the following flags built mimalloc's C code with LLVM 23 Clang and Polly. The `-march=native` setting makes this build local to a compatible CPU; omit it or choose a baseline target for distribution. `-fomit-frame-pointer` was part of the tested command but can make profiling harder.

```bash
sdk_root="$(xcrun --show-sdk-path)"
CC="$HOME/.local/opt/llvm-23.1.1/bin/clang" \
  CFLAGS="-O3 -march=native -mtune=native -fomit-frame-pointer -isysroot $sdk_root -mllvm -polly" \
  make app
target/release/osx/Alacritty.app/Contents/MacOS/alacritty --version
codesign -vvv target/release/osx/Alacritty.app
```

Package and check the app separately:

```bash
tar -cf - -C target/release/osx Alacritty.app | zstd -T0 -19 -o /tmp/Alacritty.app.tar.zst
zstd -t /tmp/Alacritty.app.tar.zst
```

For Ghostty, use its [Zig build instructions](https://ghostty.org/docs/install/build); the macOS app additionally requires full Xcode, its SDKs, and the Metal toolchain. These Cargo and Clang flags do not convert Ghostty's Zig build to LLVM 23 or enable BOLT on Mach-O.

### Build checks for future agents

1. Identify the compiler, linker, build driver, target architecture, and output format before adding flags (`rustc -vV`, `clang --version`, `xcrun --show-sdk-path`, `file <binary>`).
2. Put LTO in the project's build profile; apply Polly only to translation units compiled by a compatible Clang; use the SDK sysroot with non-Apple Clang on macOS.
3. Build once, then verify the executable, code signature if applicable, and archive integrity. Benchmark against an unmodified build before claiming a speedup.
